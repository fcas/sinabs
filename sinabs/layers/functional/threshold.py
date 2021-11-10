from typing import Optional

import torch
from torch.onnx.symbolic_opset9 import floor, div, relu


class ThresholdSubtract(torch.autograd.Function):
    """
    Subtract from membrane potential on reaching threshold
    """

    @staticmethod
    def forward(ctx, data, threshold=1, window: Optional[float] = None):
        """"""
        ctx.save_for_backward(data.clone())
        ctx.threshold = threshold
        ctx.window = window
        return (data > 0) * torch.div(data, threshold, rounding_mode="trunc").float()

    @staticmethod
    def backward(ctx, grad_output):
        """"""
        (data,) = ctx.saved_tensors
        grad = ((data >= (ctx.threshold - ctx.window)).float()) / ctx.threshold
        grad_input = grad_output * grad

        return grad_input, None, None

    def symbolic(g, data, threshold=1, window=0.5):
        """"""
        x = relu(g, data)
        x = div(g, x, torch.tensor(threshold))
        x = floor(g, x)
        return x


class ThresholdReset(torch.autograd.Function):
    """
    Threshold check
    Step hat gradient ___---___
    """

    @staticmethod
    def forward(ctx, data, threshold=1, window: Optional[float] = None):
        """"""
        ctx.save_for_backward(data)
        ctx.threshold = threshold
        ctx.window = window or threshold
        return (data >= ctx.threshold).float()

    @staticmethod
    def backward(ctx, grad_output):
        """"""
        (data,) = ctx.saved_tensors
        grad_input = grad_output * ((data >= (ctx.threshold - ctx.window)).float())
        return grad_input, None, None
