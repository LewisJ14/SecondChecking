# SC07 — complete storage configuration

Implemented locally on 22 October 2026. The owner selected **require the specified
drive configuration**: a plain 1TB requirement means one drive, not two 512GB drives.
Updated VM and physical-device acceptance/deployment remain outstanding.

## Detection

The scan enumerates `Win32_DiskDrive` once and identifies entries by device ID,
without joining partitions or requiring a mounted logical volume. Equal-size
devices remain separate; unpartitioned drives are included. Duplicate/missing IDs
and unreadable/non-positive capacity produce incomplete evidence and REVIEW.

Each record retains device ID, serial, raw bytes, model, interface/bus, media type,
type source and exclusion reason. USB/removable media are excluded from the laptop
configuration but retained in the evidence. This includes USB interface, USB PNP
identifiers, serial-matched USB bus evidence and removable-media markers.

Media type comes from optional `MSFT_PhysicalDisk` evidence joined by an exact,
unique trimmed serial. An absent/ambiguous serial match or unavailable provider
means Unknown type; it never defaults to HDD or infers SSD from a model name.
Explicit SSD/HDD/NVMe requirements cannot pass on unknown required type evidence.
NVMe requirements check both SSD media and NVMe bus evidence.

Microsoft documents the physical disk class and byte capacity:
[Win32_DiskDrive](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-diskdrive).
Media/bus classifications are documented separately:
[MSFT_PhysicalDisk](https://learn.microsoft.com/en-us/windows-hardware/drivers/storage/msft-physicaldisk).

## Comparison policy

- Compare drive count, each capacity, and each explicitly requested media/bus type.
  Drive order is irrelevant. Matching uses a bounded bipartite algorithm, including
  mixed typed and generic requirements of the same capacity.
- Examples: `512GB + 512GB`, `512GB SSD + 1TB HDD`, `2x512GB SSD`, and
  `NVMe SSD 512GB`. A bare capacity does not specify media type merely because the
  legacy database field is named `SSD`.
- GB/TB use decimal units; GiB/TiB use binary units. Retain the earlier compatibility
  aliases 1024/2048/4096/8192GB as nominal 1/2/4/8TB in legacy text. Raw measured
  byte counts are not rewritten through these aliases.
- The chosen implementation tolerance is 1% per drive, with a 1GB floor for
  reporting variation. 480GB or 500GB does not satisfy 512GB. Validate this tolerance
  against the bench's supported models before release; it does not permit a
  different drive count or substitute a summed capacity.
- Ambiguous strings, alternative layouts, missing measurements and incomplete
  inventories remain REVIEW. Legacy text helper calls can compare complete text
  configurations, but the app's comparison requires structured physical evidence.

Legacy SKU extraction now preserves all recognised storage components, count and
type instead of the first keyword. If an explicit multi-drive SKU conflicts with a
single-component admin/dropdown/custom requirement, the app marks it ambiguous;
correct the mapping rather than silently collapsing the layout. A generic matching
capacity mapping does not erase a more specific media/bus requirement in the SKU.

## Review and saved results

The comparison row is labelled Storage and shows drive components on separate
lines. The footer and row use the same comparator. Assignment receives the resolved
item requirements, including custom-item details, rather than deriving a potentially
different requirement from the SKU alone.

Final review identifies the required/measured configuration and mismatch reason.
A mismatch or unknown measurement requires an exception reason under the existing
SC04 policy. Structured inventory is stored in `specs.Storage`, alongside the legacy
`SSD` label; `storage_review` retains policy, requirement, outcome and detail. Existing
JSON fields suffice: **no database migration is needed**.

The server validates the recorded storage-review format and requires a reason for
a reported mismatch. It preserves inventory/review and returns them through the
saved-results API. This is not independent server hardware discovery. Retry intent
ignores changed capture timestamps alone while preserving changed drive evidence.

## Verification and remaining acceptance

83 desktop tests passed on the Python 3.12 packaging runtime, including equal-size
and unpartitioned drives, mixed types, USB/UASP/removable exclusion, unavailable
type providers, invalid capacity/IDs, complete spec-scan integration, strict layout,
unit conversion, tolerance, SKU extraction, assignment review and retry identity.
Actual hidden Tk controls prove REVIEW for one required versus two detected drives,
and MATCH for the corresponding two-drive requirement.

26 isolated SQLite Flask tests passed, including negative storage review reason
enforcement and inventory/review persistence/readback. No new MariaDB acceptance
run or physical scan was performed. Compilation/whitespace checks accompany this
source change. No updated executable was installed in the VM or published.

Before release, compare one-drive, equal-size dual-drive and mixed-drive laptops,
an unpartitioned internal disk, USB/UASP media and unavailable type providers.
OS-visible disk evidence cannot by itself prove the underlying physical layout of
an opaque RAID/controller/virtual-storage arrangement; these require explicit bench
validation. The VM is not proof of physical storage classification.

Storage currently follows the existing specification cache. SC08 retains the work
to refresh measurements and make capture age/source clear across the whole app.
Package the matching desktop/server together for acceptance; SC08 is next.
