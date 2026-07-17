"""Repositórios de acesso ao banco (padrão Repository).

Isolam SQL do resto da aplicação: o pipeline e a GUI só conhecem dataclasses.
"""
from __future__ import annotations

import json

from src.database.db import get_connection
from src.models.domain import CutCandidate, Project
from src.utils.logger import get_logger

logger = get_logger("repository")


class ProjectRepository:
    """CRUD de projetos e seus cortes."""

    # ------------------------------------------------------------------ #
    @staticmethod
    def save(project: Project) -> int:
        """Insere (ou atualiza) o projeto e todos os seus cortes."""
        with get_connection() as conn:
            if project.id is None:
                cursor = conn.execute(
                    "INSERT INTO projects (title, source_path, source_url, duration, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (project.title, project.source_path, project.source_url,
                     project.duration, project.status),
                )
                project.id = cursor.lastrowid
            else:
                conn.execute(
                    "UPDATE projects SET title=?, status=?, duration=? WHERE id=?",
                    (project.title, project.status, project.duration, project.id),
                )
                conn.execute("DELETE FROM cuts WHERE project_id=?", (project.id,))
            for cut in project.cuts:
                conn.execute(
                    "INSERT INTO cuts (project_id, title, description, hashtags, "
                    "category, start, end, score, reason, output_path, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (project.id, cut.title, cut.description,
                     json.dumps(cut.hashtags, ensure_ascii=False), cut.category,
                     cut.start, cut.end, cut.score, cut.reason,
                     cut.output_path, cut.status),
                )
        logger.info("Projeto #%s salvo com %d cortes.", project.id, len(project.cuts))
        return int(project.id)

    # ------------------------------------------------------------------ #
    @staticmethod
    def list_all() -> list[Project]:
        """Histórico de projetos (mais recentes primeiro), sem os cortes."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [
            Project(
                id=r["id"], title=r["title"], source_path=r["source_path"],
                source_url=r["source_url"], duration=r["duration"],
                status=r["status"], created_at=r["created_at"],
            )
            for r in rows
        ]

    @staticmethod
    def get_cuts(project_id: int) -> list[CutCandidate]:
        """Todos os cortes de um projeto."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM cuts WHERE project_id=? ORDER BY score DESC",
                (project_id,),
            ).fetchall()
        return [
            CutCandidate(
                start=r["start"], end=r["end"], title=r["title"],
                description=r["description"] or "",
                hashtags=json.loads(r["hashtags"] or "[]"),
                category=r["category"] or "geral", score=r["score"],
                reason=r["reason"] or "", output_path=r["output_path"],
                status=r["status"],
            )
            for r in rows
        ]

    @staticmethod
    def delete(project_id: int) -> None:
        """Remove um projeto e seus cortes (CASCADE)."""
        with get_connection() as conn:
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        logger.info("Projeto #%d removido.", project_id)
