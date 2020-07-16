#  Copyright (c) 2019-2019     aiCTX AG (Sadique Sheik, Qian Liu).
#
#  This file is part of sinabs
#
#  sinabs is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  sinabs is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with sinabs.  If not, see <https://www.gnu.org/licenses/>.

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from functools import reduce
from operator import mul
from .iaf import SpikingLayer
from typing import Optional, Union, List, Tuple
from ..cnnutils import conv_output_size
from torch.nn import functional

# - Type alias for array-like objects
ArrayLike = Union[np.ndarray, List, Tuple]


class SpikingConv1dLayer(SpikingLayer):
    def __init__(
        self,
        channels_in: int,
        image_shape: int,
        channels_out: int,
        kernel_shape: int,
        dilation: int = 1,
        strides: int = 1,
        padding: ArrayLike = (0, 0),
        bias: bool = True,
        threshold: float = 1.0,
        threshold_low: Optional[float] = -1.0,
        membrane_subtract: Optional[float] = None,
        membrane_reset: Optional[float] = None,
        layer_name: str = "conv1d",
    ):
        """
        Spiking 1D convolutional layer

        :param channels_in: Number of input channels
        :param image_shape: length of input sequence. This parameter name is used to maintain consistency with 2d and 3d layers
        :param channels_out: Number of output channels
        :param kernel_shape: int Size of the kernel
        :param dilation: int kernel dilaiton,
        :param strides: Strides in length
        :param padding: Padding in each of the 6 directions (left, right)
        :param bias: If this layer has a bias value
        :param threshold: Spiking threshold of the neuron
        :param threshold_low: Lower bound for membrane potential
        :param membrane_subtract: Upon spiking, if the membrane potential is subtracted as opposed to reset, \
        what is the subtracted value? Defaults to threshold.
        :param membrane_reset: What is the reset membrane potential of the neuron. \
        If not None, the membrane potential is reset instead of subtracted on spiking.
        :param layer_name: Name of this layer
        """
        SpikingLayer.__init__(
            self,
            input_shape=(channels_in, image_shape),
            threshold=threshold,
            threshold_low=threshold_low,
            membrane_subtract=membrane_subtract,
            membrane_reset=membrane_reset,
            layer_name=layer_name,
        )
        self.conv = nn.Conv1d(
            channels_in,
            channels_out,
            kernel_size=kernel_shape,
            dilation=dilation,
            stride=strides,
            bias=bias,
        )

        # Layer convolutional properties
        self.channels_in = channels_in
        self.channels_out = channels_out
        self.kernel_shape = kernel_shape
        self.dilation = dilation
        self.padding = padding
        self.strides = strides
        self.bias = bias

    def synaptic_output(self, input_spikes: torch.Tensor) -> torch.Tensor:
        """
        This method convolves the input spikes to compute the synaptic input currents to the neuron states

        :param input_spikes: torch.Tensor input to the layer.
        :return:  torch.Tensor - synaptic output current
        """
        # Convolve all inputs at once
        if self.padding == (0, 0):
            syn_out = self.conv(input_spikes)
        else:
            # Zeropadded input
            syn_out = self.conv(
                functional.pad(input_spikes, self.padding, mode="constant", value=0)
            )
        return syn_out

    def summary(self) -> pd.Series:
        """
        Returns a summary of the current layer

        :return: pandas Series object
        """
        summary = pd.Series(
            {
                "Type": self.__class__.__name__,
                "Layer": self.layer_name,
                "Output_Shape": self.output_shape,
                "Input_Shape": self.input_shape,
                "Kernel": self.kernel_shape,
                "Padding": tuple(self.padding),
                "Stride": self.strides,
                "Fanout_Prev": self.kernel_shape
                / np.array(self.strides)
                * self.channels_out,
                "Neurons": reduce(mul, list(self.output_shape), 1),
                "Kernel_Params": self.channels_in*self.channels_out*self.kernel_shape,
                "Bias_Params": self.bias * self.channels_out,
            }
        )
        return summary

    def get_output_shape(self, input_shape) -> Tuple:
        """
        Returns the shape of output, given an input to this layer

        :param input_shape: (channels, height, width)
        :return: (channelsOut, height_out, width_out)
        """
        (channels, length) = input_shape

        length_out= conv_output_size(
            length + sum(self.padding[1]),
            (self.dilation * (self.kernel_shape - 1) + 1),
            self.strides,
        )
        return self.channels_out, length_out
