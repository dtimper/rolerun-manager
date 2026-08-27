from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from app.azahar_rpc import AzaharRPCClient
from app.xy_live import (
    XYLiveReader,
    XY_PARTY_ADDRESS,
    XY_PARTY_COUNT_ADDRESS,
    XY_PARTY_COUNT_SIZE,
    XY_PARTY_RUNTIME_SPAN,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("--start", type=lambda value: int(value, 0), default=0x08C00000)
    parser.add_argument("--size", type=lambda value: int(value, 0), default=0x00100000)
    args = parser.parse_args()

    output_dir = Path(__file__).resolve().parent
    with AzaharRPCClient(timeout=1.2, retries=3) as client:
        process = XYLiveReader._find_xy_process(client.process_list())
        client.set_process(process.process_id)
        region = client.read_memory(args.start, args.size)
        party = client.read_memory(XY_PARTY_ADDRESS, XY_PARTY_RUNTIME_SPAN)
        raw_count = client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE)

    region_path = output_dir / f"{args.label}_guest_{args.start:08X}_{args.size:X}.bin"
    party_path = output_dir / f"{args.label}_party.bin"
    metadata_path = output_dir / f"{args.label}_metadata.json"
    region_path.write_bytes(region)
    party_path.write_bytes(party)
    metadata_path.write_text(
        json.dumps(
            {
                "process_id": process.process_id,
                "title_id": f"{process.title_id:016X}",
                "process_name": process.name,
                "region_start": f"0x{args.start:08X}",
                "region_size": args.size,
                "region_sha256": hashlib.sha256(region).hexdigest(),
                "party_sha256": hashlib.sha256(party).hexdigest(),
                "party_count": struct.unpack("<I", raw_count)[0],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(metadata_path.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
