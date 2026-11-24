# Preload the Google and MongoDB Atlas Terraform providers

`Status: Providers unavailable` means initialization exhausted its retries after
transient provider-download failures. Provider schema validation has not passed.
This is independent of cloud-account permissions. No infrastructure is deployed.

From the project directory, use the project's Python environment:

```powershell
.\.venv\Scripts\python.exe scripts/install_validation_provider.py --provider google
.\.venv\Scripts\python.exe scripts/install_validation_provider.py --provider mongodbatlas
```

The installer uses the official Terraform Registry download metadata and HTTPS,
checks the package against the publisher's SHA256SUMS, validates ZIP integrity,
and writes the package to `tools/provider-mirror`. The default versions are Google
6.50.0 and MongoDB Atlas 1.41.2, matching the reported failing provider versions
and compatible with the attached draft's major-version constraints. A different
draft may need another version supplied through `--version`.

If the network blocks downloads, download both the ZIP and checksum list using an
approved browser/network. Do not extract the ZIP.

For Windows AMD64:

| Provider | Download files |
|---|---|
| [Google 6.50.0 official releases](https://releases.hashicorp.com/terraform-provider-google/6.50.0/) | `terraform-provider-google_6.50.0_windows_amd64.zip` and `terraform-provider-google_6.50.0_SHA256SUMS` |
| [MongoDB Atlas 1.41.2 official release](https://github.com/mongodb/terraform-provider-mongodbatlas/releases/tag/v1.41.2) | Expand Assets: `terraform-provider-mongodbatlas_1.41.2_windows_amd64.zip` and `terraform-provider-mongodbatlas_1.41.2_SHA256SUMS` |

For example, if the four downloaded files are in the Windows Downloads folder:

```powershell
.\.venv\Scripts\python.exe scripts/install_validation_provider.py --provider google --archive "C:\Users\vinoth.rajendran\Downloads\terraform-provider-google_6.50.0_windows_amd64.zip" --checksums "C:\Users\vinoth.rajendran\Downloads\terraform-provider-google_6.50.0_SHA256SUMS"

.\.venv\Scripts\python.exe scripts/install_validation_provider.py --provider mongodbatlas --archive "C:\Users\vinoth.rajendran\Downloads\terraform-provider-mongodbatlas_1.41.2_windows_amd64.zip" --checksums "C:\Users\vinoth.rajendran\Downloads\terraform-provider-mongodbatlas_1.41.2_SHA256SUMS"
```

After both installations succeed, click **Validate with Terraform CLI** again.
The app uses its project mirror automatically. Successful downloads do not imply
that the Terraform itself passes validation; that is the subsequent check.

Run the installer inside the same machine/container as the app. Linux containers
require Linux packages, not Windows ZIPs. TLS verification remains enabled.
