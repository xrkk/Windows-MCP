# Filesystem error diagnostics

Filesystem failures retain the operation, resolved source path, optional
destination path, exception class, errno, WinError when supplied by Windows,
and the original OS error text (bounded to 4096 characters). The same diagnostic
is returned as an `Error:` result and written to the local server error logger.
File contents and submitted write text are not logged.

Read the native error before changing ACLs: access denial and sharing violations
can both prevent an open or copy, but require different remedies. No WinError
number is invented when Python does not supply one. A non-elevated permission
failure retains the existing elevation hint.

Portable regression checks, without native desktop imports:

```shell
python -m unittest discover -s tests/portable -p test_filesystem_diagnostics.py -v
```

The checks cover copy/move source and destination identifiers, a distinct sharing
violation, write failure without content disclosure, and unchanged successful
write/copy/move behavior. They inject native errors at the actual operation
boundary; Windows deployment acceptance must additionally exercise real ACLs.
