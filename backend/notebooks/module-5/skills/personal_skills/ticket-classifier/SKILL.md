---
name: ticket-classifier
description: Classifies customer support tickets by priority, category, and sentiment
version: 1.0.0
tags:
- support
- classification
- ticket
---

## Instructions

# Ticket Classifier

## CRITICAL: Classify immediately
You MUST classify the ticket based on available information. NEVER ask follow-up questions. If details are limited, make your best judgment and note uncertainty.

## Priority
- high: urgent, blocked, crash, down, broken, security, data loss
- medium: payment failed, billing, account issue, troubleshooting
- low: how-to, documentation, feedback

## Category
- billing: payment, refund, invoice, charge
- technical: error, bug, crash, broken
- account: login, password, profile, access
- general: anything else

## Sentiment
- frustrated: angry, demands, complaints
- neutral: factual, polite
- satisfied: positive, thank you

## Output
JSON with: priority, category, sentiment, summary, confidence
