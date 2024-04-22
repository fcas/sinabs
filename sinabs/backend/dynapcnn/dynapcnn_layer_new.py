from copy import deepcopy
from typing import Dict, Optional, Tuple, Union
from warnings import warn

import numpy as np
import torch
from torch import nn

import sinabs.activation
import sinabs.layers as sl

from .discretize import discretize_conv_spike_
from .dvs_layer import expand_to_pair


class DynapcnnLayer(nn.Module):
    """Create a DynapcnnLayer object representing a dynapcnn layer.

    Requires a convolutional layer, a sinabs spiking layer and an optional
    pooling value. The layers are used in the order conv -> spike -> pool.

    Parameters
    ----------
        conv: torch.nn.Conv2d or torch.nn.Linear
            Convolutional or linear layer (linear will be converted to convolutional)
        spk: sinabs.layers.IAFSqueeze
            Sinabs IAF layer
        in_shape: tuple of int
            The input shape, needed to create dynapcnn configs if the network does not
            contain an input layer. Convention: (features, height, width)
        pool: int or None
            Integer representing the sum pooling kernel and stride. If `None`, no
            pooling will be applied.
        discretize: bool
            Whether to discretize parameters.
        rescale_weights: int
            Layer weights will be divided by this value.
    """

    def __init__(
        self,
        dcnnl_data: dict, 
        discretize: bool,
        nodes_mapper: dict,
        rescale_weights: int = 1,       # TODO remove.
    ):
        super().__init__()
        """
        ...

        TODO
            1) need to figure out how to apply 'rescale_weights' since there are more than two poolings.
            2) currently there's no way the forward would work since there are more than two poolings.
        """
        self.lin_to_conv_conversion = False

        conv = None
        conv_node_id = None

        spk = None
        self.spk_node_id = None

        pool = []
        pool_node_id = []

        for key, value in dcnnl_data.items():
            if isinstance(key, int):
                # value has data pertaining a node (torch/sinabs layer).
                if isinstance(value['layer'], sl.IAFSqueeze):
                    spk = value['layer']
                    self.spk_node_id = key
                elif isinstance(value['layer'], nn.Linear) or isinstance(value['layer'], nn.Conv2d):
                    conv = value['layer']
                    conv_node_id = key
                elif isinstance(value['layer'], sl.SumPool2d):
                    pool.append(value['layer'])
                    pool_node_id.append(key)
                else:
                    raise ValueError(f'Node {key} has not valid layer associated with it.')
                
        if not conv:
            raise ValueError(f'Convolution layer not present.')
        
        if not spk:
            raise ValueError(f'Spiking layer not present.')
        
        spk = deepcopy(spk)
        if spk.is_state_initialised():
                spk.v_mem = spk.v_mem.data.unsqueeze(-1).unsqueeze(-1)      # expand dims.

        if isinstance(conv, nn.Linear):
            conv, conv_in_shape = self._convert_linear_to_conv(conv, dcnnl_data[conv_node_id])

            # the original `nn.Linear` output shape becomes the equivalent `nn.Conv2d` shape.
            conv_out_shape = self._update_conv_node_output_shape(
                conv_layer=conv, layer_data=dcnnl_data[conv_node_id], input_shape=conv_in_shape)

            # the I/O shapes for neuron layer following the new conv need also to be updated.
            self._update_neuron_node_output_shape(layer_data=dcnnl_data[self.spk_node_id], input_shape=conv_out_shape)

        else:
            conv = deepcopy(conv)

        # TODO have to consider that two poolings might be projecting to this conv (these lines of code are deprecated).
        # this weight rescale comes from the node projecting into this 'conv' node.
        if rescale_weights != 1:
            # this has to be done after copying but before discretizing
            conv.weight.data = (conv.weight / rescale_weights).clone().detach()

        # int conversion is done while writing the config.
        if discretize:
            conv, spk = discretize_conv_spike_(conv, spk, to_int=False)

        # consolidate layers.
        self.conv_layer = conv
        self.spk_layer = spk
        self.pool_layer = []
        if len(pool) != 0:
            for plyr in pool:
                if plyr.kernel_size[0] != plyr.kernel_size[1]:
                    raise ValueError("Only square kernels are supported")
                self.pool_layer.append(deepcopy(plyr))

    def __str__(self):
        pretty_print = ''

        pretty_print += f'(con_layer): {self.conv_layer}\n'
        pretty_print += f'(spk_layer): {self.spk_layer}\n'
        if len(self.pool_layer) != 0:
            for idx, lyr in enumerate(self.pool_layer):
                pretty_print += f'(pool_layer {idx}): {lyr}\n'

        return pretty_print

    def _convert_linear_to_conv(self, lin: nn.Linear, layer_data: dict) -> nn.Conv2d:
        """Convert Linear layer to Conv2d.

        Parameters
        ----------
            lin: nn.Linear
                Linear layer to be converted

        Returns
        -------
            nn.Conv2d
                Convolutional layer equivalent to `lin`.
        """
        self.lin_to_conv_conversion = True

        input_shape = layer_data['input_shape']

        in_chan, in_h, in_w = input_shape

        if lin.in_features != in_chan * in_h * in_w:
            raise ValueError("Shapes don't match.")

        layer = nn.Conv2d(
            in_channels=in_chan,
            kernel_size=(in_h, in_w),
            out_channels=lin.out_features,
            padding=0,
            bias=lin.bias is not None,
        )

        if lin.bias is not None:
            layer.bias.data = lin.bias.data.clone().detach()

        layer.weight.data = (
            lin.weight.data.clone()
            .detach()
            .reshape((lin.out_features, in_chan, in_h, in_w))
        )

        return layer, input_shape
    
    def _update_conv_node_output_shape(self, conv_layer: nn.Conv2d, layer_data: dict, input_shape: tuple) -> Tuple:
        """ The input shapes to nodes are extracted using a list of edges by finding the output shape of the 1st element
        in the edge and setting it as the input shape to the 2nd element in the edge. If a node used to be a `nn.Linear` 
        and it became a `nn.Conv2d`, output shape in the mapper needs to be updated, otherwise there will be a mismatch
        between its output and the input it provides to another node.
        """
        layer_data['output_shape'] = self.get_conv_output_shape(conv_layer, input_shape)

        return layer_data['output_shape']

    def _update_neuron_node_output_shape(self, layer_data: dict, input_shape: tuple) -> None:
        """ Following the conversion of a `nn.Linear` into a `nn.Conv2d` the neuron layer in the
        sequence also needs its I/O shapes uodated.
        """
        layer_data['input_shape'] = input_shape
        layer_data['output_shape'] = layer_data['input_shape']

    def get_modified_node_it(self, dcnnl_data: dict) -> Union[Tuple[int, tuple], Tuple[None, None]]:
        """ ."""
        if self.lin_to_conv_conversion:
            return self.spk_node_id, dcnnl_data[self.spk_node_id]['output_shape']
        return None, None
    
    def zero_grad(self, set_to_none: bool = False) -> None:
        return self.spk_layer.zero_grad(set_to_none)
    
    def get_conv_output_shape(self, conv_layer: nn.Conv2d, input_shape: tuple):
        # get the layer's parameters.
        out_channels = conv_layer.out_channels
        kernel_size = conv_layer.kernel_size
        stride = conv_layer.stride
        padding = conv_layer.padding
        dilation = conv_layer.dilation

        # compute the output height and width.
        out_height = ((input_shape[1] + 2 * padding[0] - dilation[0] * (kernel_size[0] - 1) - 1) // stride[0]) + 1
        out_width = ((input_shape[2] + 2 * padding[1] - dilation[1] * (kernel_size[1] - 1) - 1) // stride[1]) + 1

        return (out_channels, out_height, out_width)


    def summary(self) -> dict:                                      # TODO deprecated.
        return {
            "pool": (
                None if self.pool_layer is None else list(self.pool_layer.kernel_size)
            ),
            "kernel": list(self.conv_layer.weight.data.shape),
            "neuron": self.get_neuron_shape(),
        }

    def memory_summary(self):                                       # TODO deprecated.
        """Computes the amount of memory required for each of the components. Note that this is not
        necessarily the same as the number of parameters due to some architecture design
        constraints.

        .. math::

            K_{MT} = c \\cdot 2^{\\lceil \\log_2\\left(k_xk_y\\right) \\rceil + \\lceil \\log_2\\left(f\\right) \\rceil}

        .. math::

            N_{MT} = f \\cdot 2^{ \\lceil \\log_2\\left(f_y\\right) \\rceil + \\lceil \\log_2\\left(f_x\\right) \\rceil }

        Returns
        -------
        A dictionary with keys kernel, neuron and bias and the corresponding memory sizes
        """
        summary = self.summary()
        f, c, h, w = summary["kernel"]
        f, neuron_height, neuron_width = self.get_neuron_shape()

        return {
            "kernel": c * pow(2, np.ceil(np.log2(h * w)) + np.ceil(np.log2(f))),
            "neuron": f
            * pow(2, np.ceil(np.log2(neuron_height)) + np.ceil(np.log2(neuron_width))),
            "bias": 0 if self.conv_layer.bias is None else len(self.conv_layer.bias),
        }

    def forward(self, x):                                           # TODO deprecated.
        """Torch forward pass."""
        x = self.conv_layer(x)
        x = self.spk_layer(x)
        if self.pool_layer is not None:
            x = self.pool_layer(x)
        return x
