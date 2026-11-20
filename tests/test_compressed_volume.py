import struct
import unittest
import uuid

from uefi_firmware import AutoParser, CompressedFirmwareVolume, efi_compressor
from uefi_firmware.structs.uefi_structs import FIRMWARE_VOLUME_GUIDS
from uefi_firmware.uefi import FirmwareVolume


def make_pad_file(body):
    '''An FFS pad file (type 0xf0), which always has an all-0xff GUID.'''
    size = 24 + len(body)
    header = b"\xff" * 16 + struct.pack(
        "<HBB3sB", 0, 0xf0, 0x00, struct.pack("<I", size)[:3], 0xf8)
    return header + body


def make_volume(size=0x1000):
    '''An FFS2 firmware volume holding a single pad file.'''
    body = make_pad_file(b"vendor-A" * 4)
    block_map = struct.pack("<II", 1, size) + b"\x00" * 8
    hdrlen = FirmwareVolume._HEADER_SIZE + len(block_map)
    header = struct.pack(
        "<16s16sQ4sIHHHsB",
        b"\x00" * 16, uuid.UUID(FIRMWARE_VOLUME_GUIDS["FFS2"]).bytes_le,
        size, b"_FVH", 0, hdrlen, 0, 0, b"\x00", 2)
    return header + block_map + body + b"\xff" * (size - hdrlen - len(body))


class CompressedFirmwareVolumeTest(unittest.TestCase):

    def setUp(self):
        self.volume_data = make_volume()

    def _parse(self, compressed):
        volume = CompressedFirmwareVolume(compressed)
        self.assertTrue(volume.valid_header)
        self.assertTrue(volume.process())
        return volume

    def test_tiano_compressed_volume(self):
        compressed = efi_compressor.TianoCompress(
            self.volume_data, len(self.volume_data))
        volume = self._parse(compressed)
        self.assertEqual(volume.compression, "tiano")
        self.assertEqual(volume.data, self.volume_data)
        # The stream is consumed exactly, so a caller can advance past it.
        self.assertEqual(volume.size, len(compressed))
        files = volume.volume.firmware_filesystems[0].files
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].data, b"vendor-A" * 4)

    def test_efi_compressed_volume(self):
        compressed = efi_compressor.EfiCompress(
            self.volume_data, len(self.volume_data))
        volume = self._parse(compressed)
        self.assertEqual(volume.compression, "efi")
        self.assertEqual(volume.data, self.volume_data)

    def test_lzma_compressed_volume(self):
        compressed = efi_compressor.LzmaCompress(
            self.volume_data, len(self.volume_data))
        volume = self._parse(compressed)
        self.assertEqual(volume.compression, "lzma")
        self.assertEqual(volume.data, self.volume_data)
        # The inner volume is exposed through the FirmwareObject API.
        self.assertEqual(volume.objects, [volume.volume])
        self.assertEqual(
            volume.to_dict()["volume"]["guid"], FIRMWARE_VOLUME_GUIDS["FFS2"])

    def test_autoparser_detects_compressed_volume(self):
        compressed = efi_compressor.TianoCompress(
            self.volume_data, len(self.volume_data))
        parser = AutoParser(compressed)
        self.assertEqual(parser.type(), "CompressedFirmwareVolume")
        firmware = parser.parse()
        self.assertIsInstance(firmware, CompressedFirmwareVolume)
        self.assertTrue(firmware.volume.valid_header)

    def test_build_round_trip_and_rejects_garbage(self):
        compressed = efi_compressor.TianoCompress(
            self.volume_data, len(self.volume_data))
        volume = self._parse(compressed)
        # An unmodified volume rebuilds to the original compressed bytes.
        self.assertEqual(volume.build(), compressed)
        # Data that does not unpack to a volume is not a valid header.
        self.assertFalse(CompressedFirmwareVolume(b"\x00" * 64).valid_header)
        self.assertFalse(
            CompressedFirmwareVolume(self.volume_data).valid_header)


if __name__ == "__main__":
    unittest.main()
