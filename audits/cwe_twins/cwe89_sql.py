# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 5, ПУНКТ 30: RLS-политики (изоляция тенантов). Цель `make sql-policy-check`.
# Инвариант: доступ (`result == 1`) ТОЛЬКО при
#   `(row_tenant == req_tenant or is_public == 1) and is_deleted == 0`.
# Ожидания: rls_buggy -> BYPASS (отдаёт УДАЛЁННУЮ свою строку),
#           rls_safe  -> PROVEN (изоляция на всех путях).


# @kern:rls(row_tenant, req_tenant, is_public, is_deleted)
def rls_buggy(row_tenant, req_tenant, is_public, is_deleted):
    if row_tenant == req_tenant:
        return 1
    if is_public == 1 and is_deleted == 0:
        return 1
    return 0


# @kern:rls(row_tenant, req_tenant, is_public, is_deleted)
def rls_safe(row_tenant, req_tenant, is_public, is_deleted):
    if is_deleted == 1:
        return 0
    if row_tenant == req_tenant:
        return 1
    if is_public == 1:
        return 1
    return 0
