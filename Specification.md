The following is a specification of a python app, generate the full code base for this application in a single structured answer. Results should be good to go and be able to start right away. 

Respond with all the code at once.

# Python Docker App – Google Tasks & Google Sheets Synchronization

## Overview

This app manages recurring domestic tasks for multiple individuals.
It synchronizes tasks between **Google Sheets** (for configuration and task definitions) and **Google Tasks** (as the frontend for each user) using the **Google Tasks API**.
It supports dynamic task assignment and reassignment based on time, task completion, and user-defined behaviors.

The user will define tasks in a GSheet with task recurrence period (how many long before task should be done again), a deadline and a list of user that will be "assign" task one after the other. When a user is assign a task, the python app will inject periodically tasks in its Google Tasks Application through API call. A logic and database is needed to cycle between user, re-inject tasks in user application correctly and cycle between specific user to assign tasks. Following is the specification expected for the app.

---

## Infrastructure

* **Frontend:** Google Tasks
* **API:** Google Tasks API
* **Backend:** Python application (Dockerized)

  * Python app container
  * PostgreSQL database container
* **Configuration Source:** Google Sheets

---

## App Behavior

### 1. Initialization

On startup:

1. Fetch all content from the configured Google Spreadsheet.
2. Locate the sheet named (case-insensitive): **`configuration`**
3. Parse the following columns:

   * `name` – User name
   * `email` – Google email associated with Google Tasks
   * `consent url` – OAuth URL for user consent
   * `consent token` – Access token after user authentication

**Consent Handling Logic:**

* If `consent token` is empty:

  * Generate a new OAuth consent URL and update the `consent url` cell.
* If an API call with a token fails:

  * Generate a new URL and clear the existing token.
* If possible, the app auto-fills the token after successful auth; otherwise, users manually paste it into the spreadsheet.

---

### 2. Looping Behavior

* A global loop runs every **5 minutes** (configurable).
* On each loop:

  1. Fetch task configuration and user credentials from the spreadsheet.
  2. Retrieve current Google Tasks state from each user's account.
  3. Process all task assignment and update logic.
  4. Sleep until the next cycle.

---

### 3. Creating and Updating Tasks

1. Read all **task definition sheets** (excluding `configuration`).
2. Parse and sort tasks by category (the "Categorie" column, see below).
3. Save new task definitions into PostgreSQL.
4. Existing definitions in PostgreSQL that are no longer in the spreadsheet are retained for historical reference but ignored for new assignments. Task are identify by they name. If a task disapear for the sheet, all instance are automatically terminated and removed from user app.
5. For each task definition:

   * Identify or create the corresponding task list (matching categories) in the user's Google Tasks.
   * If credentials are not available, skip API actions—but **task instance records must still be created** in the database.

---

### 4. Task Assignment Logic

#### Expected Task Columns in Google Sheets:

| Column                            | Description                                                                           |
| --------------------------------- | ------------------------------------------------------------------------------------- |
| `Nom` \*                          | Task name in the app                                                                  |
| `Duree (affichage)`               | Displayed duration (optional)                                                         |
| `Debut (heure de debut)`          | Start time or datetime (optional)                                                     |
| `Catégorie` \*                    | Task list/category in Google Tasks (created if missing)                               |
| `Durée reproduction` \*           | Period before task is eligible to be re-executed after completion                     |
| `Durée avant passation` \*        | Max duration a user has to complete a task before reassignment                        |
| `Date début`                      | When the task becomes active (optional)                                               |
| `Acteurs` \*                      | Comma-separated list of users (must match `configuration` sheet)                      |
| `Comportement non realisation` \* | Behavior if task is overdue:<br> - `Garder`<br> - `Garder et changer`<br> - `Changer` |

> \* Mandatory fields – tasks missing these fields are skipped

#### Assignment Flow:

1. Determine which tasks require assignment or updates based on database records.
2. Fetch each user’s current Google Tasks.
3. For each task instance:

   * If it is past the **final deadline** and not completed, and behavior is `"Changer"` → mark as done and assign to the next user.
   * If task is completed and current time exceeds its completion deadline before repeat → assign again (same instance, updated the deadline and reset completed date).
   
   * If task is completed and current time **DON'T**  exceeds its completion deadline before repeat → 
   Ignore and continue
   * If task is not completed and current time exceeds the completion deadline before repeat → Ignore and update the completion deadline by adding the repeat period (or set as equal as the final deadline before next user)
   * If task is completed and current time exceeds final deadline → assign to the next user.
4. Active task instances remain unchanged across recurrences; only their deadlines, completions, and assignment history are updated.
5. Include a **unique task identifier** in the Google Tasks description to map tasks to internal instances.

---

### 5. Assignment to Next User Logic

When a task instance reaches its **final deadline**, two scenario happen:
- 1 : task is marked as completed, then it will be assigned to next user.
- 2 : the task is not marked as completed, the app evaluates whether the task should be reassigned based on its `Comportement non realisation`.

* If the value is "Garder", then task remain to user until completion and the following is ignored.

* Else the value is either:
  * `"Changer"`
  * `"Garder et changer"`

Then the following occurs:

1. **Determine next user:**

   * Look up the list of users (`Acteurs`) defined in the task definition.
   * Find the current assigned user’s position in that list.
   * Select the next user in the list.

     * If the current user is the **last**, loop back and assign to the **first** user.

2. **Create a new task instance:**

   * Use the same task definition.
   * Set (for the new task instance):

     * **Assignment time:** `now`
     * **New deadline:** `now + Durée reproduction`
     * **New final deadline:** `now + Durée avant passation`
   * Assign the task to the next user’s Google Tasks list.
   * Insert a new **task instance** in the database with the updated deadlines and assigned user.

3. **"Garder et changer" behavior:**

   * The current (previous) user **retains their incomplete task**.
   * The new user receives a **new active assignment**.
   * The previous instance remains open and is not marked as terminated.

This logic ensures continuous task cycling among users, while respecting overdue behaviors.

---

### 6. Task State & Persistence

#### PostgreSQL will include:

##### 1. **Task Definitions**

* Metadata from the spreadsheet
* Category, recurrence rules, actors, etc.

##### 2. **Task Instances**

* Persistent instance per task definition
* Fields:

  * Task definition reference
  * Assigned user
  * Assigned datetime
  * Deadline (before repeat)
  * Final deadline (before next user assignment)
  * Completion datetime (nullable)
  * Sync status with Google Tasks
  * Active/terminated status

##### 3. **Task Completion History**

* Logs each time a user completes a task
* Fields:

  * Task instance reference
  * User
  * Completion datetime
  * Trigger type (manual deletion, API-detected, reassignment, etc.)

#### Instance Lifecycle:

* Each loop:

  1. Fetch active task instances (current time < final deadline).
  2. Compare with user’s current Google Tasks.
  3. If a synced task is missing from the user’s app, mark it as completed and log the completion.
  4. If a task is completed and the repetition delay has passed, update it with new deadlines and reassign if needed.
  5. If final deadline has passed and the task is not completed, run the **Assignment to Next User Logic**.

---

### 7. Code Expectations

* **Constants:** All fixed strings and identifiers go in `constants.py`
* **Configurable Parameters:** Use `.env` or config file for environment-specific values
* **Dockerized App:** Python code runs inside a Docker container
* **Secrets Management:** No credentials in Git. Inject via Google Sheet or manual copy into project root before build
* **Data Integrity:** Use DTO classes to structure payloads and validate data flow
* **Testing:** Include unit tests for core components
* **Modular Codebase:**

  * `GoogleApiHandler` – Manages Google Tasks API interactions
  * `GSheetHandler` – Manages GSheet reads and writes
  * `TaskManager` – Coordinates logic between tasks, deadlines, reassignments, and persistence
* **Persistence Layer:**

  * Maintain history of task completions and instance state transitions
* **Documentation:** Use top-level function docstrings (description, arguments, return types)


