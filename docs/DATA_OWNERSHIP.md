# Data Ownership & Domain Model Allocation

## Core Principles
1. **No Shared Databases:** Each platform owns its database domain.
2. **Single Source of Truth:**
   - **FlowWink:** Master for Customers, Products, Pricelists, Inventory, Quotes, Orders, Draft Invoices, Content, SEO, Documents, Agent Memory & Objectives.
   - **Chatwoot:** Master for Conversational Contacts, Inboxes, Conversations, Messages, Attachments, Internal Notes, Human Agent Assignments.
   - **Activepieces:** Master for External Workflow Automation triggers, executions, and connection credentials.
   - **Bridge API:** Master for Cross-domain Idmapping, Idempotency keys, Audit trail, Approvals queue, Model usage tracking, and Cost metrics.
