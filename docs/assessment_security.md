# Assessment and AI security boundary

Cloud discovery credentials remain in the application's session/process memory.
They are not passed to AI as authentication credentials. The configured AI key
authenticates only to the configured AI endpoint.

Before AI requests, the application redacts recognized sensitive fields and
credential assignments, private keys, bearer tokens and URL signatures. Entered
cloud credential values are also filtered from evidence and outgoing conversation
text even when embedded in an ordinary description. Credential dataclasses omit
secret fields from their representations. AI HTTP redirects are blocked, HTTPS is
required, and Responses requests set `store: false`. This request setting does not
override the endpoint operator's retention or logging policy.

Resource identifiers, configuration, dependencies and billing information remain
available to the configured AI service. Redaction is not anonymization and is not
a guarantee against every possible secret encoding. Use an approved AI endpoint.

Generation and automatic CLI validation do not apply infrastructure changes.
Validation excludes cloud credentials, external executable data sources,
provisioners, external modules and remote state backends, and restricts providers.
Azure native source reconstruction reads resources and uses a temporary import
plan; permission-limited records remain explicitly unverified. Cloud key-reading
permissions can expose data-access credentials and should be narrowly scoped.

Use a dedicated discovery identity with read access and only the explicitly
required additional actions. Do not grant deployment rights to the assessment
identity. Use the app's Clear entered credentials control after assessment.
Protect filled tfvars, Terraform state and saved plans; sensitive variable markers
do not encrypt files. Deployment is a separate user action with a separate identity.

These application safeguards are not a hosting security certification. Restrict
application access, require HTTPS and authentication at the hosting layer, review
the configured AI provider's data policy, and perform environment-specific security
testing before organizational production use.
