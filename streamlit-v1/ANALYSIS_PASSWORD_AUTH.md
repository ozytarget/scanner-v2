# ANÁLISIS DETALLADO - Password Authentication Flow

## 1. ESTRUCTURA DEL PROYECTO

```
c:\Users\urbin\SCANNER\
├── app.py                    # Streamlit app con autenticación
├── Dockerfile                # Build para Railway (SIN volúmenes persistentes)
├── railway.json              # Config de Railway
├── entrypoint.sh             # Script de inicio
├── .env                       # Variables locales (INITIAL_PASSWORDS configurada)
├── .env.example               # Template (sin secretos)
├── auth_data/
│   ├── passwords.db          # BD SQLite con hashes bcrypt
│   ├── users.db
│   └── backups/
└── requirements.txt           # Dependencias Python
```

## 2. CICLO DE VIDA EN RAILWAY

### Primer Deploy:
1. Dockerfile crea contenedor vacío
2. `COPY . .` copia código (incluye .env NO, porque está en .gitignore ✓)
3. `RUN mkdir -p auth_data cache` → crea carpeta vacía
4. App inicia → `initialize_passwords_db()` se ejecuta
5. Lee `INITIAL_PASSWORDS` desde Railway Dashboard
6. Crea 40 hashes bcrypt en `auth_data/passwords.db`
7. App funciona ✓

### Segundo Deploy (redeploy):
1. **NUEVO CONTENEDOR** - filesystem limpio
2. `auth_data/passwords.db` **NO EXISTE** (sin volúmenes persistentes)
3. App inicia → `initialize_passwords_db()` se ejecuta
4. Lee `INITIAL_PASSWORDS` desde Railway Dashboard
5. **¿Está `INITIAL_PASSWORDS` en Railway Dashboard?** ← **CRÍTICO**
6. Si SÍ → Crea 40 hashes nuevamente ✓
7. Si NO → BD vacía ✗ → Autenticación falla

## 3. PROBLEMAS POTENCIALES IDENTIFICADOS

### Problema #1: Dockerfile sin volúmenes
- BD no persiste entre deploys
- Solución: Agregar `VOLUME` al Dockerfile

### Problema #2: Railway variable not confirmed
- `.env` se encuentra en .gitignore (CORRECTO, no se copia a Railway)
- `INITIAL_PASSWORDS` DEBE estar en Railway Dashboard
- **NECESARIO: Verificar que realmente está configurada en Railway**

### Problema #3: authenticate_password() puede tener issues
- Línea 197: `bcrypt.checkpw(input_pwd_bytes, hashed_pwd_bytes)`
- Localmente funciona ✓
- En Railway: ¿variables de entorno diferentes? ¿contenedor diferente?

## 4. VALIDACIÓN LOCAL COMPLETADA

```
✓ spy11    → Match found in hash #40
✓ tsla79   → Match found in hash #1
✓ aapl06   → Match found in hash #2  
✓ coin77   → Match found in hash #30
```

Todas las contraseñas verifican correctamente en `bcrypt.checkpw()`

## 5. CHECKLIST ANTES DE DEPLOY

- [ ] Confirmar que `INITIAL_PASSWORDS` está en Railway Dashboard
- [ ] Agregar `VOLUME /app/auth_data` al Dockerfile (opcional, para persistencia)
- [ ] Verificar que la BD se crea correctamente en Railway (revisar logs)
- [ ] Hacer test manual con `spy11` en https://ozy.up.railway.app/
- [ ] Si falla: Revisar Railway Deploy Logs → Build Logs → HTTP Logs
