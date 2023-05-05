import pytest
import sinabs
import sinabs.backend.dynapcnn as sdl
from hw_utils import (
    is_device_connected, 
    is_any_samna_device_connected, 
    find_open_devices,
    get_ones_network,
    reset_all_connected_boards
)


@pytest.mark.skipif(not is_any_samna_device_connected(), reason="No samna device found!")
def test_deploy_dynapcnnnetwork():
    import time, torch
    import numpy as np
    from numpy.lib import recfunctions

    # at the beginning of the test make sure the boards are reset.
    reset_all_connected_boards()

    devices = find_open_devices()
    dtype = np.dtype([("x", np.uint16), ("y", np.uint16), ("t", np.uint64), ("p", bool),])
    single_event = recfunctions.unstructured_to_structured(np.array([[0,0,0,0]]), dtype)
    model = get_ones_network()
    
    sinabs.reset_states(model)
    assert model.sequence[1].conv_layer.weight.sum() == 127
    assert model.sequence[1].spk_layer.spike_threshold == 127
    assert model.sequence[1].spk_layer.v_mem.sum() == 0
    model_output = model(torch.ones((1, 1, 1, 1)))
    assert model_output.sum() == 1

    for device_name, device_info in devices.items():
        print("Testing on", device_name)
        # for speck2e and speck2f, layer #0 and #1 might not pass this test
        # see: https://hardware.basket.office.synsense.ai/documentation/speck-v2e-datasheet/sections/architecture/convolutional-layer.html#parallel-computing-layers
        n_cores = 5 if "tiny" in device_name else 9
        for core_idx in range(2, n_cores):
            if device_name in [
                "speck2e",
                "speck2edevkit", 
                "speck2f", 
                "speck3"
            ] and core_idx < 2: 
                continue
            print(f"Testing on core: {core_idx}")
            model.to(
                device=device_name, 
                chip_layers_ordering=[core_idx],
                monitor_layers=[-1]
            )
            model.reset_states()
            first_layer_idx = model.chip_layers_ordering[0] 
            factory = sdl.chip_factory.ChipFactory(device_name)
            event = factory.xytp_to_events(single_event, first_layer_idx, reset_timestamps=False)
            time.sleep(1)
            print(f"Input event: {event}")
            output = model(event)
            print(f"Num output events: {len(output)}")
            assert len(output) == 1

@pytest.mark.skipif(not is_any_samna_device_connected(), reason="No samna device found!")
def test_deploy_with_device_id():
    # Reset boards
    reset_all_connected_boards()
    model = get_ones_network()
    device_map = find_open_devices()
    print(device_map)
    device_name = list( device_map.keys() )[0]
    print(device_name)
    device_name = f"{device_name}:0"
    assert model.to(device_name)
