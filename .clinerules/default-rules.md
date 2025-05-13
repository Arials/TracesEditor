# Cline Rules - Frontend MUI Conventions

This document outlines conventions for using Material UI (MUI) components in the frontend, based on analysis of existing pages like `AsyncPage.tsx`.

## 1. Imports

- Use direct named imports for components from `@mui/material`.
- Use direct named imports for icons from `@mui/icons-material`.

```typescript
// Example
import {
  Box,
  Typography,
  Paper,
  Grid, // If using Grid
  Button,
  IconButton,
  Chip,
  Tooltip,
  Alert,
  CircularProgress,
  LinearProgress,
  Table,
  TableCell,
  // etc.
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import DeleteIcon from '@mui/icons-material/Delete';
// etc.
```

## 2. Layout

- Use the `Box` component as the primary tool for layout structure, spacing, and flexbox arrangements.
  - Apply padding using `sx={{ p: <number> }}`.
  - Apply margins using `sx={{ m: <number> }}`, `sx={{ mt: <number> }}`, `sx={{ mb: <number> }}`, etc.
  - Use `sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: <number> }}` for flex layouts.
- Use `Paper` as a container/background for distinct UI sections (e.g., forms, tables, information blocks). Apply padding within the `Paper` using `sx`.
  - Example: `<Paper sx={{ p: 2, mb: 3 }}>...</Paper>`
- For tabular data, use `TableContainer`, `Table`, `TableHead`, `TableBody`, `TableRow`, `TableCell`.
  - Wrap the `Table` in `<TableContainer component={Paper}>`.
- If using `Grid` layout (MUI v5+ / Grid v2):
  - Use `<Grid container spacing={2}>...</Grid>` for the main container.
  - For direct children of a `Grid container`, apply responsive props directly: `<Grid xs={12} sm={6} md={4}>...</Grid>`. The `item` prop is generally not required for direct children in Grid v2.

## 3. Styling

- Prefer the `sx` prop for component-specific, one-off style overrides or adjustments.
- For more complex or reusable styles, consider defining style objects separately or using styled-components/emotion if adopted project-wide.

## 4. Common Component Usage

- **Typography:**
  - Always specify the `variant` (e.g., "h4", "h6", "body1", "body2", "caption").
  - Use `gutterBottom` prop for standard bottom margin on headings/paragraphs.
- **Button:**
  - Specify `variant` ("contained", "outlined", "text").
  - Specify `color` ("primary", "secondary", "error", etc.).
  - Specify `size` ("small", "medium", "large"). Default is "medium".
  - Use `startIcon` or `endIcon` for icons within buttons.
  - Use the `disabled` prop for conditional disabling.
  - For navigation, use `component={RouterLink}` and `to="/path"`.
- **IconButton:**
  - Use for actions represented solely by an icon.
  - Specify `size` ("small", "medium", "large").
  - Specify `color`.
  - Use the `disabled` prop.
  - **Always** wrap `IconButton`s with a `Tooltip`.
- **Tooltip:**
  - Provide a descriptive `title`.
  - If the child element (like an `IconButton`) can be disabled, wrap the child element in a `<span>` to ensure the tooltip still triggers on hover.
    ```typescript
    <Tooltip title="Delete Item">
      <span> {/* Wrapper needed for disabled button */}
        <IconButton onClick={handleDelete} disabled={isDeleting}>
          <DeleteIcon />
        </IconButton>
      </span>
    </Tooltip>
    ```
- **Chip:**
  - Use for status indicators, tags, etc.
  - Specify `label`, `color`, and `size="small"`.
- **Alert:**
  - Use for user feedback (errors, warnings, info, success).
  - Specify `severity`.
- **Progress Indicators:**
  - `CircularProgress`: For indeterminate loading states.
  - `LinearProgress`: For determinate progress. Use `variant="determinate"` and `value={progressPercentage}`. Often combined with `Box` and `Typography` to show the percentage text.
- **Table Components:**
  - Use standard structure: `TableContainer > Table > TableHead > TableRow > TableCell` and `TableBody > TableRow > TableCell`.
  - In `TableBody`, the first `TableCell` in a row should typically have `component="th"` and `scope="row"`.
- **TextField:**
    - Specify `label`, `variant` ("outlined", "filled", "standard"), `size` ("small", "medium"), `value`, `onChange`, `disabled`, `error`, `helperText` as needed.
    - Use `sx={{ flexGrow: 1 }}` within flex containers if needed.

## 5. DataGrid (MUI X)

- **Dependency Versioning:**
  - Prefer stable release versions of `@mui/x-data-grid` (and other dependencies, especially UI components) over pre-release/alpha/beta versions to ensure stability and avoid unexpected behavior or breaking changes. For example, use `^7.0.0` instead of `^8.1.0-beta` if the latter causes issues.
- **Controlled Checkbox Selection:**
  - To implement controlled checkbox selection:
    - Maintain a state variable for selected row IDs, typically `GridRowId[]`.
      ```typescript
      const [selectedRows, setSelectedRows] = useState<GridRowId[]>([]);
      ```
    - Pass this state array directly to the `rowSelectionModel` prop of the `DataGrid`.
      ```typescript
      <DataGrid
        // ... other props
        checkboxSelection
        rowSelectionModel={selectedRows}
        onRowSelectionModelChange={(newSelectionModel: GridRowSelectionModel) => {
          // The newSelectionModel is GridRowId[] when checkboxSelection is true
          setSelectedRows(newSelectionModel as GridRowId[]);
        }}
        getRowId={(row) => row.yourStableIdField} // Ensure you have a stable ID for rows
      />
      ```
    - The `onRowSelectionModelChange` callback will provide the new array of selected `GridRowId`s. Update your state with this array.
    - Ensure `getRowId` prop is provided to the `DataGrid` to specify a stable unique identifier for each row.

## 6. Forms

- Group form elements within `Box` or `Paper`.
- Use `TextField`, `Select`, `Checkbox`, `RadioGroup`, etc., for inputs.
- Manage form state using React `useState`.
- Provide clear `label`s for all inputs.
- Use `Button`s for form submission or cancellation.

*This document should be updated as new patterns emerge or conventions evolve.*
