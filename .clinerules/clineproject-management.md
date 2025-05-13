# Cline Rules - Project Management with .clineprojects

## 1. Introduction
This rule defines the structure and conventions for project management using the `.clineprojects` system. This system replaces and expands the functionality of the former `.clineplans`.

## 2. Directory Structure
- All projects will be managed within the root directory `.clineprojects/`.
- Each project will reside in its own subdirectory: `.clineprojects/<project-name-slug>/`.
  - The `<project-name-slug>` must be lowercase, with no spaces (use hyphens), and descriptive.
- The primary project definition file will be `project.md` within its respective directory.

## 3. `project.md` File Format
The `project.md` files must adhere to the template and syntax defined in the reference documentation (or include the template here).
Key syntax points:
- Use Markdown.
- Defined sections for Description, Scope, Milestones, Phases, and Tasks.
- Tasks numbered hierarchically (e.g., `Task 1.1`, `Task 1.2.1`).
- Explicit status for Project, Milestones, Phases, and Tasks (e.g., `[STATUS: PENDING]`, `[STATUS: IN PROGRESS]`, `[STATUS: COMPLETED]`).

### `project.md` Template Snippet (Illustrative)
```markdown
# Project: [Descriptive Project Name]

**Project ID:** (Optional, e.g., PJ-2025-001)
**Creation Date:** YYYY-MM-DD
**Owner(s):** [Name/Team]
**Overall Project Status:** [PLANNING | IN PROGRESS | ON HOLD | COMPLETED | CANCELED]
**Priority:** [HIGH | MEDIUM | LOW]
**Estimated Deadline:** (Optional) YYYY-MM-DD

## 1. General Description and Objectives
(Brief project overview, problem solved, or value added.)

## 2. Scope
### 2.1. In Scope
- Item 1
### 2.2. Out of Scope
- Item 1

## 3. Key Milestones
- **MILESTONE-01:** [Description] - [STATUS: PENDING] - (Target Date: YYYY-MM-DD)

## 4. Detailed Phases and Tasks

### Phase 1: [Phase Name, e.g., Research and Design]
  **Phase Objective:** [Description]
  **Phase Status:** [PENDING | IN PROGRESS | COMPLETED]

  1.  **Task 1.1:** [Concise task description] [STATUS: PENDING]
      *   **Details:** (Additional info, acceptance criteria)
      *   **Assignee:** (Cline / Name)
      *   **Estimate:** (e.g., 2h, 1d, S, M, L)
      *   **Dependencies:** (e.g., Task 2.3)
      *   **Task Priority:** (e.g., High, Medium, Low)
      *   **Notes:** (Task-specific comments)
```

## 4. Interaction with Cline
- To request work on a project, reference the `project.md` file and specific tasks by their numbering.
  - Example: "Cline, plan tasks 4.1 to 4.3 of the project at `.clineprojects/improve-backend-performance/project.md`."
- Cline should be instructed to update the status of tasks in the `project.md` file upon completion.
  - Example: "Cline, mark Task 4.1 as COMPLETED in `.clineprojects/improve-backend-performance/project.md`."

## 5. Completion Marking (Adapting from `clineplan-task-completion-marking.md`)
- **Project Complete:** The `Overall Project Status` field in `project.md` is updated to `COMPLETED`.
- **Milestone Complete:** The milestone's status in `project.md` is updated to `COMPLETED`.
- **Phase Complete:** The phase's status in `project.md` is updated to `COMPLETED`.
- **Task Complete:** The task's status (e.g., `[STATUS: PENDING]`) is updated to `[STATUS: COMPLETED]`.
  - Additional notes about completion can be added if necessary, e.g., `[STATUS: COMPLETED] - Verified in production.`

## 6. Transition from `.clineplans`
- The `.clineplans/` directory and its contents are considered obsolete. It is recommended to archive them or migrate relevant plans to the new `.clineprojects/` format.
- The rule `.clinerules/clineplan-task-completion-marking.md` is superseded by the guidelines in this section (Point 5).
