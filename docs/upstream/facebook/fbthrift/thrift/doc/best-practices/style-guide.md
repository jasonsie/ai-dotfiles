> Source: https://github.com/facebook/fbthrift/blob/main/thrift/doc/best-practices/style-guide.md
> Mirror maintained by .github/workflows/sync-cli-docs.yml — do not edit by hand.
> License: Apache-2.0

# Style Guide

The following naming style **should** be used in all Thrift IDL files for consistency and clarity.

## Naming

Use snake case for file names, as they function like "module" names when included in other Thrift files, for example: `standard.thrift`, `security_domain.thrift.`

Use upper camel case (PascalCase) for type and service names.

- `struct MyStruct { ... }`, not `myStruct`
- `typedef int MyInt`, not `my_int`

Use lower camel case for identifiers.

- `1: string tierName`, not `tier_name`

Don’t capitalize acronyms; they follow the same camel-case rules.

- `serviceId`, not `serviceID`
- `service HttpServer { ... }`, not `HTTPServer`

When types are impractical for dimensional values, include units, for example `ttlMs` instead of `ttl`.
