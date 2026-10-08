# Completed Windows-MCP artifact handoff

`Export-VeloArtifacts.ps1` is an explicit producer completion step invoked
through PowerShell. It uses the deployed Velo repository's
`export_transfer_artifacts.ps1`; it adds no MCP tool or startup switch.
FileSystem write/copy/move success does not establish that a report/application
has finished writing. Close every selected writer and keep the producer
quiescent until the handoff ends.

Prepare deployment variables as absolute Windows paths: `$WindowsMcpRepository`,
`$VeloRepository`, `$PolicyPath`, `$OutputRoot`, `$SourceRoot`, `$Files` and
`$EvidenceDirectory`. `$Files` is a nonempty array of existing file paths strictly
below `$SourceRoot`; it is not a wildcard or a directory. `$OutputRoot` is an
existing dedicated exact Velo policy `read_roots` entry, disjoint from source
originals, work state and private configuration. Prepare its directory creation
rights for the producing administrator/SYSTEM and service Read/traverse. Use a
new `$BatchId` (1–64 ASCII letters/digits/underscore/hyphen/dot, first character
alphanumeric) and nonempty `$References` recording the actual producer jobs and
closure evidence. Do not put credentials in these references.

```powershell
& (Join-Path $WindowsMcpRepository 'Export-VeloArtifacts.ps1') `
  -VeloRepository $VeloRepository -PolicyPath $PolicyPath -OutputRoot $OutputRoot `
  -SourceRoot $SourceRoot -Files $Files -BatchId $BatchId `
  -EvidenceDirectory $EvidenceDirectory -References $References `
  -ProducerComplete -ProducerQuiescent
```

The completion switches are caller assertions backed by the retained references;
they do not close writers or inspect a larger producer's job state. The wrapper
retains `<BatchId>.export.json` with size/SHA-256 and calls the shared exporter.
That exporter refuses reparse paths and existing destinations, reads sources
without writer/delete sharing, verifies independent copy bytes, binds a
`handoff-receipt.json`, configures/verifies service Read on the completed batch,
and publishes it. Source originals and their ACLs remain producer-owned.

Submit the returned `output_directory` to the existing Velo host pull coordinator
using the configured connection profile and new transfer identity. Export success
is not transfer COMPLETE: retain the coordinator's durable result, destination
content/SHA-256 verification and both owned cleanup results. Keep the export and
producer evidence according to the reviewed retention manifest.

On failure, preserve the selected source, manifest, failed owned stage and error
JSON before deciding whether a new batch is appropriate. A held writer can yield
a sharing conflict even with correct Read ACLs; a private same-volume move or
replacement can change the final object's ACL. The exporter handles the independent
copy instead of changing the original object's security. Windows-MCP OS failures
retain operation, source/destination, exception type and native error fields in
diagnostics without logging write contents.

For shared export policy/diagnostic details and private configuration replacement,
consult `docs/artifact-export-handoff.md` and `docs/service-file-updates.md` in the
deployed Velo repository. Real deployment and end-to-end acceptance are tracked
there in `docs/cross-account-permission-implementation.md`; this documentation
alone does not close those gates. No VM reboot or snapshot restore is needed.
