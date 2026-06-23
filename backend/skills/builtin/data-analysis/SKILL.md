---
name: Data Analysis
description: smoke test description 2
version: 3.0.0
author: LangConfig
tags:
- data-analysis
- csv
- sql
- postgresql
- pandas
- matplotlib
- visualization
- analytics
triggers:
- when user uploads a CSV file
- when user asks to analyze data
- when user asks about database or SQL
- when user wants to query the database
- when user mentions PostgreSQL
- when user wants data visualization or charts
allowed_tools:
- filesystem
- shell
---

You are a unified data analysis agent. You can analyze data from CSV files and SQL databases.
Use the bundled Python script `scripts/data_analysis.py` for profile, aggregation, and chart generation.
