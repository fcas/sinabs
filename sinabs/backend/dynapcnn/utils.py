import torch.nn as nn
from typing import List, Optional
from copy import deepcopy
from .dynapcnnlayer import DynapcnnLayer
from .dvslayer import DVSLayer
import sinabs.layers as sl


def construct_dvs_layer(layers: List[nn.Module]) -> (DVSLayer, int):
    ...


def merge_conv_bn(conv, bn):
    """
    Merge a convolutional layer with subsequent batch normalization

    Parameters
    ----------
        conv: torch.nn.Conv2d
            Convolutional layer
        bn: torch.nn.Batchnorm2d
            Batch normalization

    Returns
    -------
        torch.nn.Conv2d: Convolutional layer including batch normalization
    """
    mu = bn.running_mean
    sigmasq = bn.running_var

    if bn.affine:
        gamma, beta = bn.weight, bn.bias
    else:
        gamma, beta = 1.0, 0.0

    factor = gamma / sigmasq.sqrt()

    c_weight = conv.weight.data.clone().detach()
    c_bias = 0.0 if conv.bias is None else conv.bias.data.clone().detach()

    conv = deepcopy(conv)  # TODO: this will cause copying twice

    conv.weight.data = c_weight * factor[:, None, None, None]
    conv.bias.data = beta + (c_bias - mu) * factor

    return conv


def expand_to_pair(value) -> (int, int):
    return (value, value) if isinstance(value, int) else value


def construct_next_pooling_layer(layers: List[nn.Module]) -> (Optional[sl.SumPool2d], int, float):
    """
    Consolidate the first `AvgPool2d` objects in `layers` until the first object of different type.

    Parameters
    ----------
        layers: Sequence of layer objects
            Contains `AvgPool2d` and other objects.

    Returns
    -------
        lyr_pool: int or tuple of ints
            Consolidated pooling size.
        idx_next: int or None
            Index of first object in `layers` that is not a `AvgPool2d`,
            or `None`, if all objects in `layers` are `AvgPool2d`.
        rescale_factor: float
            Rescaling factor needed when turning AvgPool to SumPool. May
            differ from the pooling kernel in certain cases.
    """
    rescale_factor = 1
    lyr_pool = None

    cumulative_pooling = (1, 1)

    idx_next = 0
    # Figure out pooling dims
    for idx_next, lyr in enumerate(layers):
        if isinstance(lyr, nn.AvgPool2d):
            if lyr.padding != 0:
                raise ValueError("Padding is not supported for the pooling layers")
        elif isinstance(lyr, sl.SumPool2d):
            ...
        else:
            # Reached a non pooling layer
            break

        pooling = expand_to_pair(lyr.kernel_size)
        stride = expand_to_pair(lyr.stride)
        if pooling != stride:
            raise ValueError("Stride length should be the same as pooling kernel size")
        # Compute cumulative pooling
        cumulative_pooling = (
            cumulative_pooling[0] * pooling[0],
            cumulative_pooling[1] * pooling[1]
        )
        # Update rescaling factor
        rescale_factor *= pooling[0] * pooling[1]

    # If there are no layers
    if cumulative_pooling == (1, 1):
        return None, idx_next, 1
    else:
        lyr_pool = sl.SumPool2d(cumulative_pooling)
        return lyr_pool, idx_next, rescale_factor


def construct_next_dynapcnn_layer(
        layers: List[nn.Module], in_shape: (int, int, int), discretize: bool, rescale_factor: float,
) -> (DynapcnnLayer, int, float):
    """
    Generate a DynapcnnLayer from a Conv2d layer and its subsequent spiking and
    pooling layers.

    Parameters
    ----------

        layers: sequence of layer objects
            First object must be Conv2d, next must be a SpikingLayer. All pooling
            layers that follow immediately are consolidated. Layers after this
            will be ignored.
        in_shape: tuple of integers
            Shape of the input to the first layer in `layers`. Convention:
            (input features, height, width)
        discretize: bool
            Discretize weights and thresholds if True
        rescale_factor: float
            Weights of Conv2d layer are scaled down by this factor. Can be
            used to account for preceding average pooling that gets converted
            to sum pooling.

    Returns
    -------
        dynapcnn_layer: DynapcnnLayer
            DynapcnnLayer
        layer_idx_next: int
            Index of the next layer after this layer is constructed
        rescale_factor: float
            rescaling factor to account for average pooling

    """
    layer_idx_next = 0  # Keep track of layer indices

    # Check that the first layer is Conv2d, or Linear
    if not isinstance(layers[layer_idx_next], (nn.Conv2d, nn.Linear)):
        raise Exception("The list of layers needs to start with Conv2d or Linear.")

    # Identify and consolidate conv layer
    lyr_conv = layers[0]
    layer_idx_next += 1
    # Check and consolidate batch norm
    if isinstance(layers[layer_idx_next], nn.BatchNorm2d):
        lyr_conv = merge_conv_bn(lyr_conv, layers[layer_idx_next])
        layer_idx_next += 1

    # Check next layer exists
    try:
        lyr_spk = layers[layer_idx_next]
        layer_idx_next += 1
    except IndexError as e:
        raise TypeError("Convolution must be followed by spiking layer. End of network found.")

    # Check that the next layer is spiking
    # TODO: Check that the next layer is an IAF layer
    if not isinstance(lyr_spk, sl.SpikingLayer):
        raise TypeError(
            f"Convolution must be followed by spiking layer, found {type(lyr_spk)}"
        )

    lyr_pool, i_next, rescale_factor_after_pooling = construct_next_pooling_layer(layers[layer_idx_next:])
    # Increment layer index to after the pooling layers
    layer_idx_next += i_next

    # Compose DynapcnnLayer
    dynapcnn_layer = DynapcnnLayer(
        conv=lyr_conv,
        spk=lyr_spk,
        pool=lyr_pool,
        in_shape=in_shape,
        discretize=discretize,
        rescale_weights=rescale_factor,
    )

    return dynapcnn_layer, layer_idx_next, rescale_factor_after_pooling
