import io
import json
import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scan_home_metadata import initial_stats, process_record, split_complete_lines  # noqa: E402


class ScanTests(unittest.TestCase):
    def test_split_lines_across_ranges_exactly_once(self):
        data = b'{"title":"Blender"}\n{"title":"Air Fryer"}\n{"title":"Rice Cooker"}'
        chunks = (data[:9], data[9:31], data[31:])
        pending = b""
        lines = []
        for index, chunk in enumerate(chunks):
            completed, pending = split_complete_lines(pending, chunk, index == len(chunks) - 1)
            lines.extend(completed)
        self.assertEqual(lines, data.splitlines())
        self.assertEqual(pending, b"")

    def test_bad_json_does_not_stop_next_record(self):
        stats = initial_stats()
        output = io.StringIO()
        ids, candidate_ids, family_ids = [], [], []
        process_record(b"{bad json}", stats, ids, candidate_ids, family_ids, output)
        process_record(
            json.dumps({"parent_asin": "A1", "title": "Air Fryer", "categories": []}).encode(),
            stats, ids, candidate_ids, family_ids, output,
        )
        self.assertEqual(stats["invalid_records"], 1)
        self.assertEqual(stats["total_records_scanned"], 2)
        self.assertEqual(stats["total_candidates"], 1)
        self.assertEqual(json.loads(output.getvalue())["candidate_family"], "air_fryer")


if __name__ == "__main__":
    unittest.main()
