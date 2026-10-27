"""Evidence-derived presentation; AI prose never supplies dashboard metrics."""
from collections import Counter


def assessment_counts(resources, plan):
    rows = [p.to_dict() if hasattr(p, "to_dict") else p for p in plan]
    return {"resources": len(resources),
            "strategies": dict(Counter(p.get("strategy") or "Review" for p in rows)),
            "waves": dict(sorted(Counter(p.get("wave", 1) for p in rows).items()))}


def render_assessment(target, resources, mapping, plan, summary):
    import streamlit as st
    import pandas as pd
    counts = assessment_counts(resources, plan)
    st.write(f"{counts['resources']} resources assessed for {target}. Proposed mappings require configuration and workload validation before migration.")
    cards = st.columns(4)
    cards[0].metric("Resources assessed", counts["resources"])
    coverage = summary.get("coverage_pct")
    cards[1].metric("Pricing coverage", f"{coverage:.1f}%" if isinstance(coverage, (int, float)) else "Unavailable")
    # Existing component summaries do not prove matching workload scope.
    cards[2].metric("Overall savings", "Not established")
    cards[3].metric("Deployment readiness", "Validation required")
    st.caption("Pricing coverage can include partial component estimates. It is not configuration equivalence or complete workload coverage.")
    left, right = st.columns(2)
    with left:
        st.write("Migration approach")
        if counts["strategies"]:
            st.bar_chart(pd.DataFrame(list(counts["strategies"].items()), columns=["Strategy", "Resources"]).set_index("Strategy"))
    with right:
        st.write("Migration waves")
        if counts["waves"]:
            st.bar_chart(pd.DataFrame([(f"Wave {k}", v) for k,v in counts["waves"].items()], columns=["Wave", "Resources"]).set_index("Wave"))
    st.caption("Counts come from the deterministic migration plan. A proposed wave or strategy does not establish readiness.")
    groups = Counter((r.get("Current Service", "Unknown"), r.get("Target Service", "Review required"),
                      r.get("Target Configuration Status", "Validation required")) for r in mapping)
    if groups:
        st.write("Service mapping and assessment status")
        st.dataframe(pd.DataFrame([{"Current service": k[0], "Proposed target": k[1], "Assessment": k[2], "Resources": v}
                                  for k,v in groups.items()]), hide_index=True, use_container_width=True)
    st.write("Priorities before migration")
    for item in ["Validate deployment configuration: storage and network attachments, private DNS, access rules and encryption.",
                 "Complete target designs for managed services using workload, compatibility and capacity evidence.",
                 "Complete pricing with matching regions, periods and component scope before claiming savings.",
                 "Run functional, performance and security pilots; establish cutover and rollback procedures."]:
        st.markdown("- " + item)
