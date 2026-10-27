"""One primary AWS recommendation; not a claim of identical service semantics."""
def recommend_aws(resource):
    kind = getattr(resource, "canonical_type", "other")
    cfg = getattr(resource, "configuration", {}) or {}
    db = cfg.get("database", {}) or {}
    if kind == "relational_database":
        engine = str(db.get("engine", "")).lower()
        if engine in {"postgres", "postgresql"}:
            return "Amazon RDS for PostgreSQL", "Preserves the engine family; validate extensions, version and instance sizing."
        if engine == "sqlserver":
            return "Amazon RDS for SQL Server", "Candidate for user databases; a logical server or Defender charge is not an RDS instance."
        return "Amazon RDS", "Database engine, edition and sizing still need confirmation."
    if kind == "nosql_database":
        evidence = str(db.get("kind", "")) + str(db.get("throughput_mode", ""))
        if "mongo" in evidence.lower():
            return "Amazon DocumentDB", "MongoDB API evidence found; validate supported operators, indexes and consistency."
        return "Amazon DynamoDB", "Proposed redesign, not a drop-in Cosmos replacement; confirm source API, key design and read/write capacity."
    return {
        "data_pipeline": ("AWS Glue", "Primary ETL candidate; job DPU-hours and connectors required. Orchestration may need additional services."),
        "app_service": ("AWS App Runner", "Candidate for a compatible stateless web app; confirm runtime/image, CPU, memory and scaling."),
        "app_service_plan": ("AWS App Runner", "Capacity is assigned per deployed service; shared Azure plan capacity cannot be copied directly."),
        "cdn": ("Amazon CloudFront", "Select a plan or supply viewer traffic and request quantities; map origins and cache behavior."),
        "machine_learning": ("Amazon SageMaker AI", "Workspace itself has no single workload price; inventory compute, endpoints and storage."),
        "generative_ai": ("Amazon Bedrock", "Select a supported model and monthly input/output tokens; model substitution requires validation."),
        "search": ("Amazon OpenSearch Service", "Confirm index compatibility, deployment type, node capacity and storage."),
    }.get(kind, (None, ""))
