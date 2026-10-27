"""Client-facing monthly planning view; preserve calculation evidence unchanged."""
import math


def planning_tables(rows):
    estimates = {"Azure": [], "AWS": []}
    review = []
    for row in rows:
        for cloud, prefix in (("Azure", "Current"), ("AWS", "AWS")):
            value = row.get(prefix + " monthly component (USD)")
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
            basis = row.get(prefix + " estimate basis", "Unresolved")
            note = row.get(prefix + " basis", "")
            common = {"Resource": row.get("Resource", ""), "Type": row.get("Type", ""),
                      "Region": row.get("Source region" if cloud == "Azure" else "AWS region", "")}
            if valid:
                estimates[cloud].append({**common, "Monthly component (USD)": value,
                    "Estimate basis": "Default assumptions" if basis == "Default assumption" else "Existing configuration / evidence" if basis == "Existing evidence" else basis,
                    "Scope and assumptions": note})
            else:
                status = basis if basis not in {"Unresolved", ""} else "Estimate pending"
                review.append({**common, "Cloud": cloud, "Status": status, "Explanation": note})
    return estimates, review


def render_monthly_planning(st, rows):
    import pandas as pd
    from .monthly_budget import budget_rows
    allowance = st.number_input("Monthly allowance per unpriced resource (USD)", min_value=0.0,
                                value=25.0, step=5.0, key="monthly_budget_allowance",
                                help="A planning reserve, not a catalog price. The same amount applies to either cloud when no estimate exists.")
    rows = budget_rows(rows, allowance)
    estimates, review = planning_tables(rows)
    st.caption("Rough budget: available estimates plus explicit allowances for unpriced resources. All inventory resources are accounted for; this does not mean every workload is fully priced. Allowances are not published service prices or a savings comparison.")
    cards = st.columns(3)
    for card, cloud in zip(cards[:2], ("Azure", "AWS")):
        priced = estimates[cloud]
        if priced:
            card.metric(cloud + " approximate budget / month", f"${sum(r['Monthly component (USD)'] for r in priced):,.2f}")
        else:
            card.metric(cloud + " approximate budget / month", "Pending")
        allowances = sum(r["Estimate basis"] == "Budget allowance (not a service price)" for r in priced)
        included = sum(r["Estimate basis"] == "No additional budget line" for r in priced)
        card.caption(f"{len(priced)}/{len(rows)} resources accounted for: {len(priced) - allowances - included} estimates, {allowances} allowances, {included} with no additional budget line.")
    cards[2].metric("Resources accounted for", f"{len(rows)}/{len(rows)}")
    cards[2].caption("Includes estimated components, explicit reserves and non-standalone items. No guaranteed savings.")
    tabs = st.tabs(["AWS budget", "Azure budget", "Budget assumptions"])
    for tab, cloud in zip(tabs[:2], ("AWS", "Azure")):
        with tab:
            if estimates[cloud]:
                st.dataframe(pd.DataFrame(estimates[cloud]), use_container_width=True, hide_index=True,
                    column_config={"Monthly component (USD)": st.column_config.NumberColumn(format="$%.6f"),
                                   "Scope and assumptions": st.column_config.TextColumn(width="large")})
            else:
                st.info(f"No {cloud} estimates are available yet. See Review items for catalog or configuration requirements.")
    with tabs[2]:
        assumptions = [{"Cloud": cloud, **entry} for cloud, entries in estimates.items() for entry in entries
                       if entry["Estimate basis"] != "Existing configuration / evidence"]
        st.caption("Default workload quantities and budget allowances are assumptions. Partial estimates can omit additional charges; the budget is not a spending cap. Unidentified resources receive an allowance rather than a fabricated rate.")
        if assumptions:
            st.dataframe(pd.DataFrame(assumptions), use_container_width=True, hide_index=True)
    st.download_button("Download full monthly assessment", pd.DataFrame(rows).to_csv(index=False),
                       "monthly_planning_assessment.csv", "text/csv", key="download_monthly_capacity")
