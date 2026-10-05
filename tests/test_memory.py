from contextlib import contextmanager
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nvidia_codec_split.core import PatchError
from nvidia_codec_split.memory import patch_regions


class FakeMemory:
    def __init__(self, failure=None):
        self.data = bytearray(b"ABCD----EFGH")
        self.failure = failure
        self.writes = 0
        self.is_suspended = False
        self.resumed = False

    @contextmanager
    def suspended(self):
        self.is_suspended = True
        try:
            yield
        finally:
            self.is_suspended = False
            self.resumed = True

    def read(self, address, size):
        return bytes(self.data[address:address+size])

    def write(self, address, data):
        if not self.is_suspended:
            raise RuntimeError("write outside suspended transaction")
        self.writes += 1
        if self.writes == self.failure:
            self.data[address:address+1] = data[:1]
            raise OSError("partial write")
        self.data[address:address+len(data)] = data


class MemoryGuards(unittest.TestCase):
    changes = [{"name":"first","rva":0,"original":b"ABCD".hex(),"patched":b"1234".hex()},
               {"name":"second","rva":8,"original":b"EFGH".hex(),"patched":b"5678".hex()}]

    def test_apply_is_idempotent_and_restore_reverses_all_regions(self):
        memory = FakeMemory()
        self.assertEqual(patch_regions(memory,self.changes,0),2)
        self.assertEqual(patch_regions(memory,self.changes,0),0)
        self.assertEqual(patch_regions(memory,self.changes,0,restore=True),2)
        self.assertEqual(memory.data,b"ABCD----EFGH")
        self.assertTrue(memory.resumed)

    def test_later_unknown_region_prevents_any_writes(self):
        memory = FakeMemory()
        memory.data[8] = ord("X")
        with self.assertRaisesRegex(PatchError,"no patch applied"):
            patch_regions(memory,self.changes,0)
        self.assertEqual(memory.writes,0)
        self.assertTrue(memory.resumed)

    def test_partial_write_rolls_back_current_and_previous_region(self):
        memory = FakeMemory(failure=2)
        with self.assertRaisesRegex(PatchError,"original bytes restored"):
            patch_regions(memory,self.changes,0)
        self.assertEqual(memory.data,b"ABCD----EFGH")
        self.assertTrue(memory.resumed)


if __name__ == "__main__":
    unittest.main()
