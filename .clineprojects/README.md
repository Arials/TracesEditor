# Project Management with `.clineprojects`

## Purpose

This directory, `.clineprojects/`, centralizes the planning and tracking of medium to long-term development projects. It replaces the older `.clineplans` system with a more robust and detailed structure, enabling better organization and collaboration with Cline (our AI assistant).

## Directory Structure

The organization is straightforward:

```
.clineprojects/
├── README.md  <-- This file
├── project-alpha-name/
│   ├── project.md
│   └── (optional: other artifacts like diagrams, notes, etc.)
├── another-important-project/
│   ├── project.md
└── ...
```

-   **`.clineprojects/`**: The root directory for all projects.
-   **`<project-name-slug>/`**: Each project resides in its own subdirectory. The name should be descriptive, lowercase, and use hyphens instead of spaces (e.g., `improve-user-interface`).
-   **`project.md`**: Within each project directory, this is the main file. It contains the entire definition, plan, and tracking for the project.

## The `project.md` File

Each `project.md` file is the heart of its respective project. It uses Markdown format for easy reading and editing. It generally includes the following sections:

1.  **General Information:** Name, ID (optional), dates, responsible parties, overall status.
2.  **Description and Objectives:** What the project aims to achieve.
3.  **Scope:** What is included and what is not.
4.  **Key Milestones:** Major deliverables or checkpoints.
5.  **Phases and Detailed Tasks:** The breakdown of work into phases and specific tasks, each with its status, assignee (can be Cline), estimation, etc. Tasks are numbered for easy reference (e.g., `Task 1.1`, `Task 2.3`).
6.  **Risks and Mitigations.**
7.  **Resources and Dependencies.**
8.  **Additional Notes.**

(Refer to the full template or an existing example to see all suggested fields.)

## How to Start a New Project

1.  Create a new subdirectory within `.clineprojects/` with a descriptive slug-formatted name (e.g., `implement-new-payment-api`).
2.  Inside that new directory, create a file named `project.md`.
3.  Copy the structure from an existing `project.md` or use the base template to fill in the details for your new project.

## Interaction with Cline

You can instruct Cline to work on specific tasks from these projects:

-   **To plan or execute tasks:**
    *   "Cline, plan tasks 1.1 to 1.3 of the project in `.clineprojects/project-alpha-name/project.md`."
    *   "Cline, start working on Task 2.1 of the `another-important-project` project." (Assuming Cline can infer the path or already knows it).
-   **To update status:**
    *   "Cline, mark Task 1.1 as COMPLETED in the `project.md` for `project-alpha-name`."

## Detailed Rules

For a complete specification of the structure, syntax, and how Cline should interact with these projects (including the exact format for completion marking), please refer to the dedicated rules file: `../../.clinerules/clineproject-management.md`. (Adjust the relative path if necessary, or simply name the file).

---
