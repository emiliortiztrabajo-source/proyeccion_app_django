# Proyección App Django

Dashboard financiero institucional reconstruido en Django a partir del flujo original en Streamlit, con autenticación, persistencia en SQLite/PostgreSQL-ready, importación desde Excel y edición de datos.

## Stack
- Django 5
- SQLite (por defecto)
- PostgreSQL opcional vía variables de entorno (`POSTGRES_*`)
- Pandas + OpenPyXL para importación inicial

## Instalación
1. Crear/activar entorno virtual
2. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Migrar base:
   ```bash
   python manage.py migrate
   ```
4. Crear superusuario:
   ```bash
   python manage.py createsuperuser
   ```
5. Crear grupos/permisos base:
   ```bash
   python manage.py bootstrap_roles
   ```

## Importación Excel
### Opción 1: comando
```bash
python manage.py import_excel_data --path "PROYECCION 2026 (4).xlsx" --scenario "ESCENARIO 1" --year 2026 --start-month 3
```

### Opción 2: web
- Ingresar con usuario staff
- Ir a `/importar-excel/`
- Subir archivo y ejecutar importación

## Correr servidor
```bash
python manage.py runserver
```

## Despliegue por Git a servidor (incluyendo datos)
Este proyecto esta preparado para desarrollo local con SQLite y despliegue en servidor con PostgreSQL.

### Regla importante
- No subir `db.sqlite3` al repositorio.
- Si queres llevar tus datos al servidor, exportalos a fixture JSON y cargalos en PostgreSQL.

### 1) Preparar cambios en tu PC
1. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Crear migraciones si hiciste cambios de modelos:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```
3. Exportar datos actuales (SQLite local):
   ```bash
   python manage.py dumpdata --exclude auth.permission --exclude contenttypes --natural-foreign --natural-primary --indent 2 > seed_data.json
   ```
4. Subir a Git:
   ```bash
   git add .
   git commit -m "Preparar deploy servidor"
   git push
   ```

### 2) Levantar en el servidor
1. Clonar o actualizar repo:
   ```bash
   git pull
   ```
2. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Configurar variables de entorno (usar `.env.example` como referencia):
   - `DJANGO_SECRET_KEY`
   - `DJANGO_DEBUG=False`
   - `DJANGO_ALLOWED_HOSTS`
   - `POSTGRES_DB`
   - `POSTGRES_USER`
   - `POSTGRES_PASSWORD`
   - `POSTGRES_HOST`
   - `POSTGRES_PORT`
4. Migrar estructura:
   ```bash
   python manage.py migrate
   ```
5. Cargar datos exportados desde tu PC (si corresponde):
   ```bash
   python manage.py loaddata seed_data.json
   ```
6. Preparar estaticos:
   ```bash
   python manage.py collectstatic --noinput
   ```

### 3) Verificacion minima
- Entrar con usuario admin.
- Validar dashboard, importaciones y tabla de gastos.
- Confirmar que CAFCI responde en red del servidor.

### 4) Actualizaciones futuras
Cuando cambies codigo:
1. `git push` desde tu PC.
2. `git pull` en servidor.
3. `pip install -r requirements.txt` (si cambian deps).
4. `python manage.py migrate`.
5. Reiniciar servicio de app.

## Usuarios y permisos
- `administrador_finanzas`: acceso completo de negocio
- `operador_finanzas`: visualización + edición de gastos/ingresos

## Estructura
- `dashboard/models.py`: entidades base
- `dashboard/services/excel_importer.py`: importador y normalización
- `dashboard/services/dashboard_logic.py`: cálculos del dashboard
- `dashboard/views.py`: vistas autenticadas, filtros y edición
- `dashboard/templates/dashboard/`: UI principal
- `dashboard/management/commands/`: bootstrap de roles + importador CLI
