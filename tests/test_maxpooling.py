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

def test_maxpool2d():
    from tensorflow import keras

    kerasLayer = keras.layers.MaxPooling2D(pool_size=(3, 3), strides=None)
    keras_config = kerasLayer.get_config()

    from sinabs.from_keras.from_keras import from_maxpool2d_keras_conf

    # Create spiking layers
    layer_list = from_maxpool2d_keras_conf(
        keras_config, input_shape=(5, 30, 50), spiking=True
    )

    for layer_name, layer in layer_list:
        print(layer_name)
        print(layer.summary())

    # Verify output shape
    assert layer.output_shape == (5, 10, 16)


def test_maxpool_function():
    from sinabs.layers import SpikingMaxPooling2dLayer
    import torch

    lyr = SpikingMaxPooling2dLayer(image_shape=(2, 3), pool_size=(2, 3), strides=None)

    tsrInput = (torch.rand(10, 1, 2, 3) > 0.8).float()
    # print(tsrInput.sum(0))
    tsrInput[:, 0, 0, 2] = 1
    tsrOut = lyr(tsrInput)

    assert tsrOut.sum().item() == 10.0

    from tensorflow import keras

    kerasLayer = keras.layers.MaxPooling2D(pool_size=(2, 2), strides=None)
    keras_config = kerasLayer.get_config()

    # Create spiking layers
