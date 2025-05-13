# Project: Backend Code Review & Refactor - May 2025

**Project ID:** BCK-REVIEW-2025-05
**Creation Date:** 2025-05-09
**Owner(s):** Cline & Adriel
**Overall Project Status:** PLANNING
**Priority:** MEDIUM
**Estimated Deadline:** (Por definir)

## 1. General Description and Objectives
Revisar el código del backend de PcapAnonymizer para identificar y documentar áreas de mejora, incluyendo código no utilizado, documentación deficiente, y desviaciones de los patrones de desarrollo establecidos (especialmente `backend-storage-path-conventions.md`). El objetivo final es tener un listado de tareas concretas para mejorar la mantenibilidad, claridad y robustez del backend. Se excluirán los archivos y funcionalidades de DICOM actualmente en depuración.

## 2. Scope
### 2.1. In Scope
- Revisión de los siguientes archivos/módulos del backend:
    - `backend/main.py`
    - `backend/anonymizer.py`
    - `backend/MacAnonymizer.py`
    - `backend/storage.py`
    - `backend/models.py`
    - `backend/database.py`
    - `backend/exceptions.py`
    - `backend/protocols/` (excluyendo `dicom/` y funcionalidades DICOM en debug)
- Identificación de código no utilizado.
- Evaluación y mejora de la documentación (docstrings, comentarios).
- Verificación del cumplimiento de `backend-storage-path-conventions.md`.
- Identificación de oportunidades para mejorar la calidad general del código (claridad, simplicidad, manejo de errores, consistencia).
- Documentación de todos los hallazgos como tareas en este proyecto.

### 2.2. Out of Scope
- Implementación de los cambios (esta fase es solo de análisis y planificación).
- Revisión de `backend/DicomAnonymizer.py`.
- Revisión de `backend/dicom_pcap_extractor.py`.
- Revisión de cualquier otra funcionalidad específica de DICOM marcada como DEBUG.
- Revisión del código frontend.
- Pruebas exhaustivas de funcionalidad (el foco es el análisis estático y de patrones).

## 3. Key Milestones
- **MILESTONE-01:** Creación del archivo de proyecto y definición del plan. - [STATUS: COMPLETED] - (Target Date: 2025-05-09)
- **MILESTONE-02:** Revisión completa de `backend/storage.py`. - [STATUS: PENDING]
- **MILESTONE-03:** Revisión completa de `backend/main.py`. - [STATUS: COMPLETED]
- **MILESTONE-04:** Revisión completa de `backend/anonymizer.py` y `backend/MacAnonymizer.py`. - [STATUS: PENDING]
- **MILESTONE-05:** Revisión completa de `backend/models.py`, `backend/database.py`, y `backend/exceptions.py`. - [STATUS: PENDING]
- **MILESTONE-06:** Revisión completa de `backend/protocols/`. - [STATUS: PENDING]
- **MILESTONE-07:** Consolidación final de todas las tareas en el `project.md`. - [STATUS: PENDING]

## 4. Detailed Phases and Tasks

### Phase 1: Review `backend/storage.py`
  **Phase Objective:** Analizar `storage.py` en busca de mejoras, código no utilizado, y correcta implementación de las convenciones de paths.
  **Phase Status:** [PENDING]

  1.  **Task STO-1:** [storage.py] Eliminar importación `os` no utilizada. [STATUS: COMPLETED]
      *   **Details:** El módulo `os` se importa pero `pathlib` maneja las operaciones de ruta.
      *   **Assignee:** Cline
      *   **Estimate:** XS
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** Limpieza menor.
  2.  **Task STO-2:** [storage.py] Reemplazar `print` por `logging` en manejo de excepciones. [STATUS: COMPLETED]
      *   **Details:** En `store_uploaded_pcap`, `read_pcap_from_session`, y `write_pcap_to_session`, los errores se imprimen en consola. Usar el módulo `logging` es preferible para producción.
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Medium
      *   **Notes:** Afecta a tres funciones.
  3.  **Task STO-3:** [storage.py] Clarificar docstring de `store_rules` sobre valor de retorno. [STATUS: COMPLETED]
      *   **Details:** El docstring de `store_rules` no menciona explícitamente que devuelve un `Path` (heredado de `store_json`).
      *   **Assignee:** (Por asignar)
      *   **Estimate:** XS
      *   **Dependencies:** None
      *   **Task Priority:** Very Low
      *   **Notes:** Mejora menor de documentación.

### Phase 2: Review `backend/main.py`
  **Phase Objective:** Analizar `main.py` (puntos de entrada API) para el cumplimiento de convenciones, manejo de errores, y claridad.
  **Phase Status:** [COMPLETED]

  1.  **Task MAIN-1:** [main.py] Implementar y usar `resolve_physical_session_details`. [STATUS: COMPLETED]
      *   **Details:** Crear la función helper `resolve_physical_session_details` según `.clinerules/backend-storage-path-conventions.md`. Actualizar todos los endpoints que operan sobre trazas (ej. `/preview`, `/subnets`, `/mac/ip-mac-pairs`, `/mac/rules`, endpoints de inicio de jobs) para usar esta función y obtener el `actual_physical_directory_id`.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** L
      *   **Dependencies:** None
      *   **Task Priority:** High
      *   **Notes:** Crítico para la correcta gestión de trazas derivadas.
  2.  **Task MAIN-2:** [main.py] Corregir paso de IDs a `storage.py` y tareas de fondo. [STATUS: COMPLETED]
      *   **Details:** Asegurar que, tras obtener el `actual_physical_directory_id` (ver MAIN-1), este ID sea el que se pase a las funciones de `storage.py` y a las funciones de tareas de fondo (`run_apply`, `run_mac_transform`, etc.) para todas las operaciones de ficheros.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** M
      *   **Dependencies:** MAIN-1
      *   **Task Priority:** High
      *   **Notes:** Consecuencia directa de MAIN-1.
  3.  **Task MAIN-3:** [main.py] Corregir `AsyncJob.session_id` al crear jobs. [STATUS: COMPLETED]
      *   **Details:** Al crear registros `AsyncJob`, el campo `session_id` debe almacenar el `actual_physical_directory_id` de la traza de entrada, no el `session_id_from_frontend` si son diferentes. `AsyncJob.trace_name` puede seguir almacenando el nombre asociado al `session_id_from_frontend`.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** M
      *   **Dependencies:** MAIN-1
      *   **Task Priority:** High
      *   **Notes:** Afecta a la creación de todos los tipos de jobs.
  4.  **Task MAIN-4:** [main.py] Refactorizar o eliminar endpoint `/download_dicom_v2/{filename}`. [STATUS: COMPLETED]
      *   **Details:** Este endpoint no usa `session_id` y es incompatible con el `storage.py` actual. Debe ser rediseñado para incluir `session_id` y usar `storage.get_session_filepath` o ser reemplazado por el endpoint genérico `/sessions/{session_id}/files/{filename}`.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Medium
      *   **Notes:** Actualmente es propenso a errores. Eliminado en favor del endpoint genérico.
  5.  **Task MAIN-5:** [main.py] Reemplazar `print()` por el módulo `logging`. [STATUS: COMPLETED]
      *   **Details:** Sustituir todas las ocurrencias de `print()` usadas para logging/debug por llamadas al módulo `logging` configurado apropiadamente.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** M
      *   **Dependencies:** None
      *   **Task Priority:** Medium
      *   **Notes:** Mejora la observabilidad y el manejo de logs en producción.
  6.  **Task MAIN-6:** [main.py] Revisar patrón de importaciones condicionales y funciones dummy. [STATUS: COMPLETED]
      *   **Details:** Evaluar si los `try/except ImportError` con definiciones de funciones dummy para `anonymizer`, `DicomAnonymizer`, etc., son necesarios. Si los módulos son críticos, la aplicación debería fallar al inicio si no se pueden importar.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** Podría simplificar el código y clarificar dependencias.
  7.  **Task MAIN-7:** [main.py] Mejorar documentación de endpoints (docstrings). [STATUS: COMPLETED]
      *   **Details:** Ampliar los docstrings de los endpoints de FastAPI para detallar parámetros (path, query, body), respuestas esperadas (con esquemas si es posible) y códigos de error comunes.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** M
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** Mejora la usabilidad de la API.
  8.  **Task MAIN-8:** [main.py] Revisar modificación de `sys.path` al inicio del script. [STATUS: COMPLETED]
      *   **Details:** Evaluar si la modificación de `sys.path` es la forma más adecuada de manejar las importaciones del proyecto o si hay alternativas (ej. estructura de paquete, ejecución desde raíz).
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Very Low
      *   **Notes:** Consideración de buenas prácticas de estructura de proyecto.
      *   **Evaluation Summary:**
          *   **Current:** `main.py` modifies `sys.path` to add the project root. This allows `from backend import ...` when `main.py` is run directly.
          *   **Assessment:** Functional for direct execution (`python backend/main.py`). However, a more standard approach for FastAPI apps is `uvicorn backend.main:app` from the project root, which often makes the `sys.path` modification redundant.
          *   **Recommendation:** The `sys.path` modification is acceptable if direct script execution is a priority. If `uvicorn backend.main:app` becomes the standard, the modification could be removed for cleaner code. Given "Very Low" priority, change is not urgent.

### Phase 3: Review `backend/anonymizer.py` and `backend/MacAnonymizer.py`
  **Phase Objective:** Analizar los módulos de anonimización.
  **Phase Status:** [COMPLETED]

  **Sub-Phase 3.1: `backend/anonymizer.py`**
  1.  **Task ANOM-1:** [anonymizer.py] Eliminar función `process_upload` redundante. [STATUS: COMPLETED]
      *   **Details:** La función `process_upload` parece ser una lógica de subida antigua, ahora manejada por el endpoint `/upload` en `main.py`. Verificar si es utilizada y, si no, eliminarla.
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Medium
      *   **Notes:** Simplificación del código.
  2.  **Task ANOM-2:** [anonymizer.py] Revisar y refactorizar la función `anon_ip` y su manejo de reglas. [STATUS: COMPLETED]
      *   **Details:** Investigar el comentario "DEBUG anon_ip: Offset issue or rule unusable". Asegurar que la lógica de aplicación de reglas y el fallback a IP aleatoria sean robustos y correctos. Considerar pasar `ip_map` como parámetro en lugar de usar global.
      *   **Assignee:** Cline
      *   **Estimate:** M
      *   **Dependencies:** None
      *   **Task Priority:** Medium
      *   **Notes:** Potencial bug o comportamiento inesperado en la anonimización de IP.
  3.  **Task ANOM-3:** [anonymizer.py] Refactorizar `apply_anonymization_response`. [STATUS: COMPLETED]
      *   **Details:** Esta función no debería re-ejecutar `apply_anonymization`. Debería servir un archivo ya anonimizado. Requiere que `main.py` pase el `output_trace_id` y `output_filename` correctos.
      *   **Assignee:** Cline
      *   **Estimate:** M
      *   **Dependencies:** MAIN-1, MAIN-2
      *   **Task Priority:** Medium
      *   **Notes:** Ineficiencia y posible comportamiento incorrecto.
  4.  **Task ANOM-4:** [anonymizer.py] Reemplazar `print()` por el módulo `logging`. [STATUS: COMPLETED]
      *   **Details:** Sustituir `print()` por llamadas a `logging` para debug y advertencias.
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Medium
  5.  **Task ANOM-5:** [anonymizer.py] Eliminar importación condicional de `storage` y `models` y `DummyStorage`. [STATUS: COMPLETED]
      *   **Details:** Estos módulos son dependencias críticas. Su ausencia debería causar un error al inicio.
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Medium
  6.  **Task ANOM-6:** [anonymizer.py] Actualizar o eliminar bloque `if __name__ == '__main__':`. [STATUS: COMPLETED]
      *   **Details:** El código de prueba en este bloque no está actualizado con las firmas de función recientes y depende de `DummyStorage`.
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Low
  7.  **Task ANOM-7:** [anonymizer.py] Asegurar consistencia en firmas de funciones con `main.py`. [STATUS: COMPLETED]
      *   **Details:** Verificar que las firmas de `apply_anonymization`, `generate_preview`, `get_subnets`, `save_rules` sean totalmente consistentes con cómo se llaman (o se llamarán tras refactorizar `main.py`).
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Dependencies:** MAIN-1, MAIN-2
      *   **Task Priority:** Medium

  **Sub-Phase 3.2: `backend/MacAnonymizer.py`**
  1.  **Task MACANOM-1:** [MacAnonymizer.py] Eliminar importaciones condicionales y fallbacks. [STATUS: COMPLETED]
      *   **Details:** Eliminar los bloques `try/except ImportError` para `storage`, `models`, y `JobCancelledException`. Estas son dependencias críticas.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Medium
  2.  **Task MACANOM-2:** [MacAnonymizer.py] Reemplazar `print()` por el módulo `logging`. [STATUS: COMPLETED]
      *   **Details:** Sustituir `print()` por llamadas a `logging` para debug, advertencias e información.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Medium
  3.  **Task MACANOM-3:** [MacAnonymizer.py] Actualizar o eliminar bloque `if __name__ == '__main__':`. [STATUS: COMPLETED]
      *   **Details:** El código de prueba en este bloque no está completamente actualizado con las firmas de función recientes (ej. `apply_mac_transformation` espera más parámetros).
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** The `if __name__ == '__main__':` block was confirmed to be absent. Decided against creating/restoring it. The functionality of `apply_mac_transformation` involves significant file system and `storage.py` dependencies, making a `__main__` block complex to implement and maintain. Such testing is better suited for dedicated unit/integration tests. The module will not include a `__main__` execution block.
  4.  **Task MACANOM-4:** [MacAnonymizer.py] Asegurar consistencia en firmas de funciones con `main.py`. [STATUS: COMPLETED]
      *   **Details:** Verificar que las firmas de `apply_mac_transformation`, `extract_ip_mac_pairs`, etc., sean totalmente consistentes con cómo se llaman (o se llamarán tras refactorizar `main.py`).
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** MAIN-1, MAIN-2
      *   **Task Priority:** Medium
      *   **Notes:** Verificación completada. No se requirieron cambios de código.
  5.  **Task MACANOM-5:** [MacAnonymizer.py] Revisar manejo de errores en `parse_oui_csv` y `validate_oui_csv`. [STATUS: COMPLETED]
      *   **Details:** Las funciones devuelven `False` o `{}` en caso de error. Considerar si deberían lanzar excepciones más específicas para ser manejadas por el llamador (ej. `main.py` para dar feedback HTTP adecuado).
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** Se crearon y utilizaron nuevas excepciones (`OuiCsvValidationError`, `OuiCsvParseError`) en `exceptions.py` y `MacAnonymizer.py`.

### Phase 4: Review `backend/models.py`, `backend/database.py`, `backend/exceptions.py`
  **Phase Objective:** Analizar los módulos de soporte de datos y errores.
  **Phase Status:** [PENDING]

  **Sub-Phase 4.1: `backend/models.py`** [STATUS: COMPLETED]
  1.  **Task MOD-1:** [models.py] Revisar exposición de rutas en `PcapSessionResponse`. [STATUS: COMPLETED]
      *   **Details:** Los campos `pcap_path` y `rules_path` en `PcapSessionResponse` exponen rutas internas del sistema. Se debe evaluar si son necesarios para el cliente o si pueden eliminarse, confiando en endpoints de descarga específicos. Los comentarios en el código (`# Keep internal path? Or remove for security? Keeping for now.`) indican una conciencia previa de este problema.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** M
      *   **Dependencies:** None
      *   **Task Priority:** Medium
      *   **Notes:** Consideración de seguridad y buenas prácticas de API. Implica los siguientes sub-pasos de análisis:
          *   **Sub-Task MOD-1.1:** Investigar el uso actual de `pcap_path` y `rules_path` en el código del frontend (ej. `UploadPage.tsx`, `api.ts`). Determinar si se usan para construir URLs de descarga o para otra lógica. [STATUS: COMPLETED] - No se encontraron usos de `pcap_path` o `rules_path` en el frontend.
          *   **Sub-Task MOD-1.2:** Basado en MOD-1.1: [STATUS: COMPLETED] - Se han comentado los campos `pcap_path` y `rules_path` en `PcapSessionResponse` en `backend/models.py` para su eventual eliminación.
              *   Si los campos NO se usan en el frontend: Planificar su eliminación directa de `PcapSessionResponse`.
              *   Si los campos SÍ se usan: Evaluar la viabilidad de refactorizar el frontend para usar endpoints de descarga genéricos (ej. `/sessions/{session_id}/files/{filename}`). Si es viable, planificar la eliminación de los campos en backend y crear una tarea de seguimiento para el frontend. Si no es viable a corto plazo, documentar el riesgo y mantener los campos temporalmente con una advertencia clara.
          *   **Sub-Task MOD-1.3:** Documentar la decisión final y las acciones a tomar (o ya tomadas) como resultado de esta tarea. [STATUS: COMPLETED] - Los campos `pcap_path` y `rules_path` han sido comentados en `backend/models.py` (marcados como `# MOD-1: Marked for removal`) debido a que no se utilizan en el frontend. Esto mejora la seguridad al no exponer rutas internas del sistema a través de la API. La eliminación definitiva se puede realizar en una fase posterior de limpieza si se confirma que no hay otros usos indirectos.
  2.  **Task MOD-2:** [models.py] Refinar tipos `Optional[Any]` en `DicomExtractedMetadata`. [STATUS: COMPLETED]
      *   **Details:** Los campos `SoftwareVersions` y `TransducerData` en `DicomExtractedMetadata` son actualmente `Optional[Any]`. Se debe investigar si se puede definir una estructura más específica (ej. `Optional[List[str]]`, `Optional[Dict[str, Any]]`, o un `BaseModel` anidado) para mejorar la validación de datos y la claridad del modelo.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** Mejora de la precisión del modelo y la robustez. Implica los siguientes sub-pasos de análisis:
          *   **Sub-Task MOD-2.1:** Investigar el origen y la estructura típica de los datos para `SoftwareVersions` y `TransducerData`. Esto puede implicar revisar el código de extracción en `backend/dicom_pcap_extractor.py` y/o analizar datos de ejemplo. [STATUS: COMPLETED] - El análisis de `dicom_pcap_extractor.py` (líneas `found_metadata['SoftwareVersions'] = p_data_ds.get("SoftwareVersions") # Can be str or list` y `found_metadata['TransducerData'] = p_data_ds.get("TransducerData") # Can be multi-valued`) indica que `pydicom` puede devolver un único valor (string) o una lista de valores (list of strings) para estos campos.
          *   **Sub-Task MOD-2.2:** Basado en MOD-2.1: [STATUS: COMPLETED] - Se han actualizado los tipos de `SoftwareVersions` y `TransducerData` en `DicomExtractedMetadata` (en `backend/models.py`) a `Optional[Union[str, List[str]]]`. Se ha añadido `Union` a las importaciones de `typing`.
              *   Si se identifica una estructura consistente y más específica: Actualizar los tipos de campo en `DicomExtractedMetadata`.
              *   Si la estructura es inherentemente variable o no se puede determinar con certeza: Documentar esta conclusión y mantener `Optional[Any]`, explicando la justificación.
          *   **Sub-Task MOD-2.3:** Documentar la decisión final y las acciones a tomar (o ya tomadas). [STATUS: COMPLETED] - Los tipos de `SoftwareVersions` y `TransducerData` en `DicomExtractedMetadata` se han actualizado a `Optional[Union[str, List[str]]]`. Esto proporciona una mayor especificidad que `Optional[Any]` basándose en la información del extractor DICOM, mejorando la claridad y la validación potencial del modelo.

  **Sub-Phase 4.2: `backend/database.py`**
  1.  **Task DB-1:** [database.py] Confirmar y documentar uso de `AsyncJob.output_trace_id`. [STATUS: PENDING]
      *   **Details:** El campo `AsyncJob.output_trace_id` (`Optional[str] = Field(default=None, foreign_key="pcapsession.id", index=True, nullable=True, description="ID of the PcapSession created as output by this job")`) ya existe en el modelo `AsyncJob` en `backend/database.py` y su descripción es adecuada. La tarea se centrará en confirmar que esta documentación es suficiente y en verificar su uso y documentación contextual en `main.py` (al crear jobs) y otras áreas relevantes.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** XS
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** Principalmente una tarea de documentación/confirmación. El campo ya existe y está bien definido en el modelo. No se prevén cambios de código en `database.py` para esta tarea específica. La revisión de su uso en `main.py` se solapará con las tareas de dicho módulo.
  2.  **Task DB-2:** [database.py] Considerar eliminar `PcapSession.rules_path` si las reglas se mueven a la BD. [STATUS: PENDING]
      *   **Details:** El campo `PcapSession.rules_path` existe y tiene comentarios tanto en el código (`# Path where the rules .json file is stored (could be removed if rules are stored in DB)`) como en el `project.md` sobre su posible eliminación si las reglas se mueven a la base de datos. Esta tarea es una consideración para una refactorización mayor, no una acción inmediata.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** XS (para esta fase de revisión, solo anotar)
      *   **Dependencies:** (Decisión de diseño mayor)
      *   **Task Priority:** Very Low
      *   **Notes:** No es una acción inmediata, sino una observación para una posible refactorización futura. La decisión de mover las reglas a la BD está fuera del alcance de esta revisión. Se mantendrán los comentarios existentes.

  **Sub-Phase 4.3: `backend/exceptions.py`**
  1.  **Task EXC-1:** [exceptions.py] Confirmar existencia y uso de una excepción base para la aplicación. [STATUS: COMPLETED]
      *   **Details:** Se ha confirmado que `backend/exceptions.py` ya define una excepción base `PcapAnonymizerException(Exception)`. Otras excepciones personalizadas como `JobCancelledException`, `FileProcessingError`, y `CsvProcessingError` ya heredan de ella directa o indirectamente.
      *   **Assignee:** Cline
      *   **Estimate:** XS
      *   **Dependencies:** None
      *   **Task Priority:** Very Low
      *   **Notes:** La estructura base de excepciones ya está implementada.
  2.  **Task EXC-2:** [exceptions.py] Identificar y definir excepciones personalizadas adicionales. [STATUS: PENDING]
      *   **Details:** Durante la revisión de otros módulos, se han identificado oportunidades para excepciones más específicas. Esta tarea consiste en definir estas nuevas excepciones en `exceptions.py`.
          *   **EXC-2.1 (Identificado):** `OuiCsvValidationError` y `OuiCsvParseError` ya existen y son buenos ejemplos.
          *   **EXC-2.2 (Propuesta):** Definir `StorageError(FileProcessingError)` para errores genéricos de E/S en `storage.py` (ej. fichero no encontrado, error de permisos).
          *   **EXC-2.3 (Propuesta):** Definir `InvalidRuleFormatError(PcapAnonymizerException)` para errores en la validación/parseo de ficheros de reglas (ej. en `anonymizer.py`, `MacAnonymizer.py`).
      *   **Assignee:** (Por asignar)
      *   **Estimate:** S
      *   **Dependencies:** None
      *   **Task Priority:** Low
      *   **Notes:** Para un manejo de errores más granular. La implementación de *lanzar* estas excepciones se realizará en las tareas de refactorización de los módulos correspondientes (`storage.py`, `anonymizer.py`, etc.). Esta tarea solo cubre su definición en `exceptions.py`.

### Phase 5: Review `backend/protocols/`
  **Phase Objective:** Analizar los manejadores de protocolos (excluyendo DICOM).
  **Phase Status:** [PENDING]

  1.  **Task PROTO-1:** [protocols] Decidir y planificar el destino de la estructura de protocolos vacía (BACnet y base). [STATUS: PENDING]
      *   **Details:** Los archivos `backend/protocols/base.py`, `backend/protocols/bacnet/handler.py`, y `backend/protocols/bacnet/utils.py` están actualmente vacíos. La funcionalidad DICOM (en `backend/protocols/dicom/`) está fuera del alcance de esta limpieza inmediata.
      *   **Assignee:** (Por asignar)
      *   **Estimate:** XS
      *   **Dependencies:** None
      *   **Task Priority:** Very Low
      *   **Notes:**
          *   Se ha confirmado que los siguientes archivos están vacíos:
              *   `backend/protocols/base.py`
              *   `backend/protocols/bacnet/handler.py`
              *   `backend/protocols/bacnet/utils.py`
          *   **Recomendación de Plan:**
              *   Eliminar `backend/protocols/bacnet/handler.py`.
              *   Eliminar `backend/protocols/bacnet/utils.py`.
              *   Eliminar `backend/protocols/bacnet/__init__.py`.
              *   Eliminar el directorio `backend/protocols/bacnet/`.
              *   Eliminar `backend/protocols/base.py` (ya que no hay otros manejadores de protocolo genéricos en desarrollo activo fuera de DICOM).
          *   Los archivos `backend/protocols/__init__.py` y `backend/protocols/README.md` se mantendrán si son relevantes para la estructura `dicom/` existente.
          *   Esta tarea es para decidir el plan. La ejecución de la eliminación se realizaría en una fase de implementación.
