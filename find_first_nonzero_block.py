#!/usr/bin/env python3
"""
Find the first non-zero 4K block on a disk device using binary search.
This assumes there's a pattern where zero blocks transition to non-zero blocks.
"""

import os
import sys
import subprocess

BLOCK_SIZE = 4096  # 4K blocks


def _run_command(cmd, timeout=5):
    """Run a command and return stdout, or None on error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _read_proc_file(filepath):
    """Read a /proc or /sys file, return content or None on error."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except (OSError, IOError):
        pass
    return None


def _check_mounts(device_path, device_name):
    """Check if device is mounted."""
    content = _read_proc_file('/proc/mounts')
    if content:
        for line in content.splitlines():
            if device_path in line or device_name in line:
                parts = line.split()
                if len(parts) > 1:
                    return f"Device is MOUNTED at {parts[1]}"
    return None


def _check_filesystem(device_path):
    """Check for filesystem signature using blkid."""
    output = _run_command(['blkid', device_path])
    if output:
        return f"Device has filesystem signature: {output}"
    return None


def _check_lvm(device_path):
    """Check if device is an LVM physical volume."""
    output = _run_command(['pvs', '--noheadings', device_path])
    if output:
        return f"Device is an LVM physical volume: {output}"
    return None


def _check_device_mapper(device_path, device_name):
    """Check if device is used by device-mapper."""
    output = _run_command(['dmsetup', 'info'])
    if output and (device_path in output or device_name in output):
        return "Device is in use by device-mapper (dm/LVM)"
    return None


def _check_raid(device_name):
    """Check if device is part of RAID."""
    content = _read_proc_file('/proc/mdstat')
    if content and device_name in content:
        return "Device is part of a RAID array (md)"
    return None


def _check_holders(device_name):
    """Check if device has holders (other devices using it)."""
    holders_path = f"/sys/block/{device_name}/holders"
    try:
        if os.path.exists(holders_path):
            holders = os.listdir(holders_path)
            if holders:
                return f"Device has holders (in use by): {', '.join(holders)}"
    except (OSError, IOError):
        pass
    return None


def _check_swap(device_path):
    """Check if device is used as swap."""
    content = _read_proc_file('/proc/swaps')
    if content and device_path in content:
        return "Device is in use as SWAP"
    return None


def check_device_usage(device_path):
    """
    Check if the device is in use by LVM, filesystems, mount points, etc.
    Returns a list of warnings if the device is in use.
    """
    device_name = os.path.basename(device_path)

    checks = [
        _check_mounts(device_path, device_name),
        _check_filesystem(device_path),
        _check_lvm(device_path),
        _check_device_mapper(device_path, device_name),
        _check_raid(device_name),
        _check_holders(device_name),
        _check_swap(device_path),
    ]

    return [warning for warning in checks if warning is not None]


def get_device_size(fd):
    """Get the size of the disk device in bytes."""
    # Seek to the end to get the size
    size = os.lseek(fd, 0, os.SEEK_END)
    return size


def is_block_zeroed(fd, block_num):
    """Check if a 4K block is all zeros."""
    offset = block_num * BLOCK_SIZE
    os.lseek(fd, offset, os.SEEK_SET)

    block_data = os.read(fd, BLOCK_SIZE)

    # Verify we read the full block
    if len(block_data) != BLOCK_SIZE:
        raise IOError(f"Failed to read full block {block_num}: "
                      f"got {len(block_data)} bytes, expected {BLOCK_SIZE}")

    # Check if all bytes are zero
    return all(byte == 0 for byte in block_data)


def find_first_nonzero_block(device_path):
    """
    Use binary search to find the first non-zero 4K block.

    Returns:
        block_num: The block number of the first non-zero block, or None if all blocks are zero
    """
    # Open device in read-only binary mode
    try:
        fd = os.open(device_path, os.O_RDONLY)
    except PermissionError:
        print( "Error: Permission denied. Try running with sudo.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: Device {device_path} not found.", file=sys.stderr)
        sys.exit(1)

    try:
        # Get device size
        device_size = get_device_size(fd)
        total_blocks = device_size // BLOCK_SIZE

        print(f"Device: {device_path}")
        print(f"Size: {device_size:,} bytes ({device_size / (1024**3):.2f} GB)")
        print(f"Total 4K blocks: {total_blocks:,}")
        print()

        if not is_block_zeroed(fd, 0):
            print("First block is non-zero - disk is not zeroed at all.")
            return 0, device_size

        # First, check the last block - if it's zero, the whole disk is zeroed
        last_block = total_blocks - 1
        if is_block_zeroed(fd, last_block):
            print("Last block is zero - entire disk is zeroed.")
            return None

        print(f"Last block is non-zero. Searching for first non-zero block...")

        # Binary search for the first non-zero block
        left = 0
        right = total_blocks - 1
        result = None

        while left <= right:
            mid = (left + right) // 2

            print(f"Checking block {mid:,} (offset {mid * BLOCK_SIZE:,} bytes)...", end="\r")

            if is_block_zeroed(fd, mid):
                # Block is zero, search right half
                left = mid + 1
            else:
                # Block is non-zero, this could be our answer
                # But check if there's an earlier non-zero block
                result = mid
                right = mid - 1

        print()  # Clear the progress line

        if result is not None:
            print( "\nFirst non-zero block found:")
            print(f"  Block number: {result:,}")
            print(f"  Byte offset: {result * BLOCK_SIZE:,}")
            print(f"  Position: {result * BLOCK_SIZE / (1024**3):.6f} GB")

            # Show a preview of the data
            os.lseek(fd, result * BLOCK_SIZE, os.SEEK_SET)
            preview_data = os.read(fd, min(64, BLOCK_SIZE))
            print(f"\nFirst 64 bytes of the block:")
            print("  " + " ".join(f"{b:02x}" for b in preview_data[:32]))
            print("  " + " ".join(f"{b:02x}" for b in preview_data[32:64]))

            # Print dd command to zero from this point onwards
            byte_offset = result * BLOCK_SIZE
            remaining_bytes = device_size - byte_offset
            print( "\nTo zero from this block onwards, run:")
            print(f"  sudo dd if=/dev/zero of={device_path} bs=4096 seek={result} status=progress")
            print(f"\nThis will write {remaining_bytes:,} bytes ({remaining_bytes / (1024**3):.2f} GB)")

        return result, device_size

    finally:
        os.close(fd)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <device_path>")
        print(f"Example: {sys.argv[0]} /dev/sda")
        print(f"         {sys.argv[0]} /dev/nvme0n1")
        sys.exit(1)

    device_path = sys.argv[1]

    # Check if device is in use
    warnings = check_device_usage(device_path)
    if warnings:
        print("WARNING: Device appears to be in use!")
        print()
        for warning in warnings:
            print(f"  ⚠️  {warning}")
        print()

        # If there's a filesystem signature, the disk is definitely not zeroed
        if any("filesystem signature" in warning for warning in warnings):
            print("Device has a filesystem signature - disk is NOT zeroed.")

        result = 0
        device_size = get_device_size(os.open(device_path, os.O_RDONLY))

    else:
        print("Proceeding with READ-ONLY scan. DO NOT run the dd command without")
        print("ensuring the device is not in use and data loss is acceptable.")
        print()
        (result, device_size) = find_first_nonzero_block(device_path)

    if result is not None:
        print( "\nFirst non-zero block found:")
        print(f"  Block number: {result:,}")
        print(f"  Byte offset: {result * BLOCK_SIZE:,}")
        print(f"  Position: {result * BLOCK_SIZE / (1024**3):.6f} GB")

        # Print dd command to zero from this point onwards
        byte_offset = result * BLOCK_SIZE
        remaining_bytes = device_size - byte_offset
        print( "\nTo zero from this block onwards, run:")
        print(f"  sudo dd if=/dev/zero of={device_path} bs=4096 seek={result} status=progress")
        print(f"\nThis will write {remaining_bytes:,} bytes ({remaining_bytes / (1024**3):.2f} GB)")

    else:
        print("All blocks are zeroed. No non-zero blocks found.")


if __name__ == "__main__":
    main()
