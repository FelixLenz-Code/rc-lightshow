from lightshow.protocol import (
    MAGIC,
    PortWire,
    build_channels,
    build_config,
    build_frame,
    crc16,
)


def test_crc16_reference_vector():
    # CRC-16/CCITT-FALSE of "123456789" is 0x29B1.
    assert crc16(b"123456789") == 0x29B1


def test_frame_layout_and_crc():
    frame = build_frame(0x01, b"\x01\x02")
    assert frame[:2] == MAGIC
    assert frame[2] == 1          # version
    assert frame[3] == 0x01       # type
    assert frame[4:6] == b"\x02\x00"
    assert frame[6:8] == b"\x01\x02"
    assert int.from_bytes(frame[8:10], "little") == crc16(frame[2:8])


def test_channels_payload():
    frame = build_channels(7, [[1000, 2000], [1500]])
    payload = frame[6:-2]
    assert payload[0] == 7        # sequence
    assert payload[1] == 2        # port count
    assert payload[2] == 2        # channels on port 0
    assert int.from_bytes(payload[3:5], "little") == 1000
    assert int.from_bytes(payload[5:7], "little") == 2000
    assert payload[7] == 1        # channels on port 1
    assert int.from_bytes(payload[8:10], "little") == 1500


def test_config_payload_marks_inverted_ports():
    ports = [
        PortWire("a", "ppm", "normal", 2, 22500, 400, 1000, 2000, [1000, 1500]),
        PortWire("b", "sbus", "inverted", 1, 7000, 0, 1000, 2000, [1200]),
    ]
    payload = build_config(ports)[6:-2]
    assert payload[0] == 2
    assert payload[1] == 1        # ppm
    assert payload[2] == 0        # not inverted
    assert payload[3] == 2        # channels
    assert int.from_bytes(payload[4:6], "little") == 22500
    # Second port starts after 11 fixed bytes plus 2 failsafe words.
    second = 1 + 11 + 4
    assert payload[second] == 2       # sbus
    assert payload[second + 1] == 1   # inverted flag


def test_config_rejects_failsafe_length_mismatch():
    ports = [PortWire("a", "ppm", "normal", 4, 22500, 400, 1000, 2000, [1000])]
    try:
        build_config(ports)
    except ValueError as exc:
        assert "failsafe" in str(exc)
    else:
        raise AssertionError("expected ValueError")
