---
name: langgraph-docs
description: Use this skill for requests related to LangGraph in order to fetch relevant documentation to provide accurate, up-to-date guidance.
---

# langgraph-docs

## Overview

This skill explains how to access LangGraph Python documentation to help answer questions and guide implementation.

## Instructions

### 1. Fetch the Documentation Index

Use the fetch_url tool to read the following URL:
https://docs.langchain.com/llms.txt

This provides a structured list of all available documentation with descriptions.

### 2. Select Relevant Documentation

Based on the question, identify 2-4 most relevant documentation URLs from the index. Prioritize:

- Specific how-to guides for implementation questions
- Core concept pages for understanding questions
- Tutorials for end-to-end examples
- Reference docs for API details

### 3. Fetch Selected Documentation

Use the fetch_url tool to read the selected documentation URLs.

### 4. Provide accurate guidance

After reading the documentation, answer the user's question using the relevant LangGraph docs you fetched.

In your response:

- Give a direct answer first.
- Include the minimum necessary context and any key steps or API names.
- Avoid quoting long passages. Paraphrase and link instead.

### 5. Provide the regular links for the used references

At the end of your response, include a **References** section listing the page URLs you used.
