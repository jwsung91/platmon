# Storage capacity

A low-frequency group ([observations.md](observations.md)): the partitions of the physical disks and the
size, use and free space of the local disk filesystems, every `[storage] interval` seconds (30 by
default). **Off by default** (`[storage] enabled = yes` turns it on). It is separate from:

- `disk` in `/api/stats`, the root filesystem's size and use, which keeps its keys and its 1 s cadence;
- `disk_io` ([disk-io.md](disk-io.md)), how busy the disks are.

```json
"storage": {
  "data": {
    "partitions": [
      {"name": "nvme0n1p1", "disk": "nvme0n1", "major": 259, "minor": 1, "size_bytes": 998643240960,
       "mount_points": ["/"]},
      {"name": "nvme0n1p2", "disk": "nvme0n1", "major": 259, "minor": 2, "size_bytes": 134217728,
       "mount_points": []}
    ],
    "filesystems": [
      {"device": "nvme0n1p1", "major": 259, "minor": 1, "fstype": "ext4", "source": "/dev/nvme0n1p1",
       "mount_points": [{"path": "/", "read_only": false}],
       "total_bytes": 982806532096, "used_bytes": 113806532096, "available_bytes": 819000000000}
    ]
  }
}
```

(The numbers show the format; they are not a measurement.)

## What is read

One read each of `/proc/partitions` and `/proc/self/mountinfo`, one `os.statvfs` per filesystem, and for
each partition one check of `/sys/class/block/<name>` (is it a partition, of which disk). Never a block
device itself: an unmounted partition's filesystem is not identified, nothing is mounted, and no
partition table is read or changed.

## Fields

- `partitions`: partitions of physical disks (the disks [disk-io.md](disk-io.md) selects): `name`, `disk`,
  `major`, `minor`, `size_bytes` (from `/proc/partitions`), and the `mount_points` of a listed local
  filesystem on it in this mount namespace (empty: not mounted here; no capacity is given for it). Partitions of virtual
  devices (loop, zram, device-mapper, md) are left out.
- `filesystems`: one entry per mounted filesystem, however many mount points show it (bind mounts are
  listed in `mount_points`, never counted twice):
  - `device`: the kernel name of its device number (`major`:`minor` from mountinfo), e.g. `nvme0n1p1` or
    `dm-0`; `null` when the number has no block device name (btrfs and some others use an anonymous
    number). `source`: the mount source as mountinfo gives it.
  - `fstype`, `mount_points` (`path`, `read_only` from that mount's options).
  - `total_bytes`, `used_bytes`, `available_bytes` from `statvfs`, as `df` computes them: total =
    blocks × fragment size, used = total − free, available = what unprivileged users can still write
    (`f_bavail`; less than total − used when blocks are reserved for root). `null` when `statvfs` failed
    (reported in `collector`), never 0; a measured 0 is 0.
- `disk`, `device` and the link between them follow the device numbers; when a filesystem sits on a
  logical volume (`dm-0`), its link to the physical partition is not resolved.

## Which filesystems

Only mounts whose source is a `/dev/` device and whose type is a local disk filesystem: `ext2`, `ext3`,
`ext4`, `xfs`, `btrfs`, `f2fs`, `vfat`, `exfat`, `ntfs3`, `jfs`, `reiserfs`. Never `statvfs`'ed:

- network and FUSE filesystems (NFS, CIFS, sshfs, ...) and autofs: a call could wait for a remote server
  or trigger an automount;
- `tmpfs`, `overlay` (a container's root), `squashfs` images (snap packages on loop devices), and pseudo
  filesystems (`proc`, `sysfs`, `cgroup`, ...): they are memory, layers or read-only images, not disk
  space.

The mount namespace is platmon's own: in a container (as in `compose.yaml`) that is the container's
mounts (its overlay root is left out; the host's root bind-mounted at `/host/root` is listed with that
path), while `/proc/partitions` lists the host's partitions. This follows from the mounts; the storage
group has not been run in a container yet. Mount points can contain names chosen by
users (`/media/<user>/...`); like the rest of the API, run platmon on trusted networks only.

## Diagnostics

`collector` ([observations.md](observations.md)) uses the optional-group rules: an unreadable
`/proc/partitions` or `/proc/self/mountinfo` (target `partitions` / `mountinfo`) leaves out what it would
have given and keeps the rest; a mountinfo line that does not parse is left out (`line<N>`, `invalid_data`);
only lines of the listed filesystem types are converted and checked (others, such as a broken tmpfs line,
are never reported); a `statvfs` that fails is reported under the filesystem's device (`disappeared` when it was unmounted in
between) and that filesystem stays listed without numbers. Nothing found at all is `unavailable`
(`not_detected`).

## Configuration

```ini
[storage]
enabled = no      ; yes: observe it
interval = 30     ; seconds between observations, 5 to 3600
```

30 s is a starting point: capacity changes slowly and the cost per observation is small (see the
performance report); it was not derived as an optimum. Shown on the web page ("Storage") and in the
`platmon` command and `/text` (`STORAGE` lines: filesystems with used / total and available, partitions
counted per disk), with the observation's age. A filesystem is shown by its first mount point and how many
more there are ("/ +60 more": bind mounts can be dozens, e.g. under Docker Desktop on WSL); the full list is
in the API.

## Not included

Unmounted filesystems' contents or types, partition tables, LVM / md topology, inode counts, quotas,
per-directory usage, network filesystems, history.
