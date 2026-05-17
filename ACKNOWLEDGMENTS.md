# Acknowledgments

## The Royal Academy of Arts

This tool is used to faciliate production of some of the printed
materials for the Royal Academy of Arts's annual **Summer Exhibition**.

References to the "Royal Academy of Arts" and the "Summer Exhibition"
in this repository are descriptive. The Royal Academy is not a licensor
of, contributor to, or sponsor of this software, and bears no
responsibility for the source code or its use.

## Open source dependencies

This project stands on a stack of open source software. The runtime
dependencies are listed in [requirements.txt](requirements.txt); the
principal ones are:

### Web framework and runtime
- **[FastAPI](https://github.com/tiangolo/fastapi)** — web framework (MIT)
- **[Starlette](https://github.com/encode/starlette)** — ASGI toolkit (BSD-3-Clause)
- **[Uvicorn](https://github.com/encode/uvicorn)** — ASGI server (BSD-3-Clause)
- **[Pydantic](https://github.com/pydantic/pydantic)** — data validation (MIT)
- **[python-multipart](https://github.com/Kludex/python-multipart)** — multipart parsing (Apache-2.0)
- **[aiofiles](https://github.com/Tinche/aiofiles)** — async file I/O (Apache-2.0)

### Data layer
- **[SQLAlchemy](https://www.sqlalchemy.org/)** — ORM and SQL toolkit (MIT)
- **[Alembic](https://alembic.sqlalchemy.org/)** — database migrations (MIT)
- **[psycopg2](https://www.psycopg.org/)** — PostgreSQL driver (LGPL-3.0-or-later)
- **[PostgreSQL](https://www.postgresql.org/)** — database (PostgreSQL Licence)

### Spreadsheet and export
- **[openpyxl](https://openpyxl.readthedocs.io/)** — Excel `.xlsx` parser (MIT)
- **Adobe InDesign Tagged Text** — export target format. Tagged Text is a
  specification published by Adobe; this project produces ASCII-MAC
  (Mac Roman) encoded output for import into InDesign layouts.

### Authentication and AWS
- **[PyJWT](https://github.com/jpadilla/pyjwt)** — JWT validation (MIT)
- **[email-validator](https://github.com/JoshData/python-email-validator)** — email syntax checks (CC0-1.0)
- **[boto3 / botocore](https://github.com/boto/boto3)** — AWS SDK for Python (Apache-2.0)
- **[AWS Cognito](https://aws.amazon.com/cognito/)** — managed user pool, JWT issuance
- **AWS ECS Fargate, RDS, S3, ALB** — production hosting

### Tooling
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** — env loading (BSD-3-Clause)
- **[pytest](https://docs.pytest.org/)** — test runner (MIT)
- **[Docker](https://www.docker.com/)** and **GitHub Actions** — packaging and CI/CD

## Licences

Each dependency remains the copyright of its respective authors and is
governed by its own licence. This project does not redistribute the
source of these dependencies; it declares them in `requirements.txt`
and installs them at build time. Please consult the linked project
homepages for the authoritative licence terms.

## Citing this work

If you build on this project or refer to it in published reporting,
research, or other software, please use the metadata in
[CITATION.cff](CITATION.cff).
