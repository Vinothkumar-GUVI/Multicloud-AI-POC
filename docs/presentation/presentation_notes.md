# Proposed rate-card demonstration

This workbook uses synthetic prices. It is not connected to the current application.

Suggested presentation wording:

> This slide illustrates a rate-card approach: predefined resource unit prices are stored in a spreadsheet. The scenario quantities are multiplied by each cloud?s corresponding unit rate, and the resource estimates are summed for comparison.

Implementation status:

> The current manual scenario uses predefined cloud adjustment factors. Spreadsheet-driven resource pricing is a proposed replacement; this workbook demonstrates its calculation design.

The workbook contains six tabs: Start Here, Rate Catalog, Resource Inputs, Cost Comparison, Dashboard and Assumptions. It includes 21 example consumption components and 63 cloud-specific synthetic rate entries. The catalog records service, configuration scope, pricing unit, region assumption, currency and validation status. The comparison selects rates using SUMIFS and calculates quantity multiplied by rate.

Open illustrative_resource_pricing.xlsx in Excel or LibreOffice. Change a yellow usage quantity in Resource Inputs or a unit rate in Rate Catalog to demonstrate recalculation of component costs and dashboard totals. Initial formula results are cached for viewers that cannot recalculate. Editing formulas or inputs in a non-calculating viewer will not refresh those results.
