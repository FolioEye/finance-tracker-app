"""FastAPI dependency-injection wiring.

No singletons or global mutable state -- a fresh repository/handler is
constructed per request from a pooled session, per constraint matrix.
"""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.application.commands.commit_import import CommitImportHandler
from apps.api.application.commands.confirm_subscription import ConfirmSubscriptionHandler
from apps.api.application.commands.create_budget import CreateBudgetHandler
from apps.api.application.commands.create_categorisation_rule import (
    CreateCategorisationRuleHandler,
)
from apps.api.application.commands.create_transaction import CreateTransactionHandler
from apps.api.application.commands.delete_budget import DeleteBudgetHandler
from apps.api.application.commands.delete_transaction import DeleteTransactionHandler
from apps.api.application.commands.detect_subscriptions_for_transaction import (
    DetectSubscriptionsForTransactionHandler,
)
from apps.api.application.commands.dismiss_alert import DismissAlertHandler
from apps.api.application.commands.dismiss_subscription import DismissSubscriptionHandler
from apps.api.application.commands.evaluate_alerts_for_transaction import (
    EvaluateAlertsForTransactionHandler,
)
from apps.api.application.commands.login_user import LoginUserHandler
from apps.api.application.commands.logout_user import LogoutUserHandler
from apps.api.application.commands.mark_not_subscription import MarkNotSubscriptionHandler
from apps.api.application.commands.register_user import RegisterUserHandler
from apps.api.application.commands.stage_import import StageImportHandler
from apps.api.application.commands.update_budget import UpdateBudgetHandler
from apps.api.application.commands.update_staged_rows import UpdateStagedRowsHandler
from apps.api.application.commands.update_transaction import UpdateTransactionHandler
from apps.api.application.queries.get_budget_overview import GetBudgetOverviewHandler
from apps.api.application.queries.get_spending_insights import GetSpendingInsightsHandler
from apps.api.application.queries.list_alerts import ListAlertsHandler
from apps.api.application.queries.list_subscriptions import ListSubscriptionsHandler
from apps.api.application.queries.list_transactions import ListTransactionsHandler
from apps.api.config import Settings, get_settings
from apps.api.domain.repositories.alert_repository import AlertRepository
from apps.api.domain.repositories.budget_repository import BudgetRepository
from apps.api.domain.repositories.categorisation_rule_repository import (
    CategorisationRuleRepository,
)
from apps.api.domain.repositories.import_staging_repository import ImportStagingRepository
from apps.api.domain.repositories.subscription_repository import SubscriptionRepository
from apps.api.infrastructure.cache.redis_client import redis_client
from apps.api.infrastructure.database.session import get_session
from apps.api.infrastructure.repositories.redis_import_staging_repository import (
    RedisImportStagingRepository,
)
from apps.api.infrastructure.repositories.sqlalchemy_alert_repository import (
    SqlAlchemyAlertRepository,
)
from apps.api.infrastructure.repositories.sqlalchemy_budget_repository import (
    SqlAlchemyBudgetRepository,
)
from apps.api.infrastructure.repositories.sqlalchemy_categorisation_rule_repository import (
    SqlAlchemyCategorisationRuleRepository,
)
from apps.api.infrastructure.repositories.sqlalchemy_subscription_repository import (
    SqlAlchemySubscriptionRepository,
)
from apps.api.infrastructure.repositories.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)
from apps.api.infrastructure.repositories.sqlalchemy_user_repository import (
    SqlAlchemyUserRepository,
)
from apps.api.infrastructure.security.password_hasher import BcryptPasswordHasher
from apps.api.infrastructure.security.rate_limiter import RedisRateLimiter
from apps.api.infrastructure.security.token_revocation import RedisTokenRevocationStore
from apps.api.infrastructure.security.token_service import TokenService


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session


def get_register_user_handler(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> RegisterUserHandler:
    repository = SqlAlchemyUserRepository(session)
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    tokens = TokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )
    return RegisterUserHandler(
        user_repository=repository,
        password_hasher=hasher,
        token_service=tokens,
        min_password_length=settings.password_min_length,
    )


def get_login_user_handler(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LoginUserHandler:
    repository = SqlAlchemyUserRepository(session)
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    tokens = TokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )
    rate_limiter = RedisRateLimiter(redis_client)
    return LoginUserHandler(
        user_repository=repository,
        password_hasher=hasher,
        token_service=tokens,
        rate_limiter=rate_limiter,
        max_attempts=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_minutes * 60,
    )


def get_logout_user_handler(settings: Settings = Depends(get_settings)) -> LogoutUserHandler:
    tokens = TokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )
    revocation_store = RedisTokenRevocationStore(redis_client)
    return LogoutUserHandler(token_service=tokens, revocation_store=revocation_store)


def get_create_transaction_handler(
    session: AsyncSession = Depends(get_db_session),
) -> CreateTransactionHandler:
    repository = SqlAlchemyTransactionRepository(session)
    return CreateTransactionHandler(transaction_repository=repository)


def get_list_transactions_handler(
    session: AsyncSession = Depends(get_db_session),
) -> ListTransactionsHandler:
    repository = SqlAlchemyTransactionRepository(session)
    return ListTransactionsHandler(transaction_repository=repository)


def get_categorisation_rule_repository(
    session: AsyncSession = Depends(get_db_session),
) -> CategorisationRuleRepository:
    return SqlAlchemyCategorisationRuleRepository(session)


def get_create_categorisation_rule_handler(
    categorisation_rules: CategorisationRuleRepository = Depends(
        get_categorisation_rule_repository
    ),
) -> CreateCategorisationRuleHandler:
    return CreateCategorisationRuleHandler(categorisation_rule_repository=categorisation_rules)


def get_update_transaction_handler(
    session: AsyncSession = Depends(get_db_session),
    categorisation_rules: CategorisationRuleRepository = Depends(
        get_categorisation_rule_repository
    ),
) -> UpdateTransactionHandler:
    repository = SqlAlchemyTransactionRepository(session)
    return UpdateTransactionHandler(
        transaction_repository=repository, categorisation_rule_repository=categorisation_rules
    )


def get_delete_transaction_handler(
    session: AsyncSession = Depends(get_db_session),
) -> DeleteTransactionHandler:
    repository = SqlAlchemyTransactionRepository(session)
    return DeleteTransactionHandler(transaction_repository=repository)


def get_import_staging_repository() -> ImportStagingRepository:
    return RedisImportStagingRepository(redis_client)


def get_stage_import_handler(
    staging: ImportStagingRepository = Depends(get_import_staging_repository),
    categorisation_rules: CategorisationRuleRepository = Depends(
        get_categorisation_rule_repository
    ),
) -> StageImportHandler:
    return StageImportHandler(
        staging_repository=staging, categorisation_rule_repository=categorisation_rules
    )


def get_update_staged_rows_handler(
    staging: ImportStagingRepository = Depends(get_import_staging_repository),
) -> UpdateStagedRowsHandler:
    return UpdateStagedRowsHandler(staging_repository=staging)


def get_commit_import_handler(
    session: AsyncSession = Depends(get_db_session),
    staging: ImportStagingRepository = Depends(get_import_staging_repository),
) -> CommitImportHandler:
    transaction_repository = SqlAlchemyTransactionRepository(session)
    return CommitImportHandler(
        staging_repository=staging, transaction_repository=transaction_repository
    )


def get_budget_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BudgetRepository:
    return SqlAlchemyBudgetRepository(session)


def get_create_budget_handler(
    budgets: BudgetRepository = Depends(get_budget_repository),
) -> CreateBudgetHandler:
    return CreateBudgetHandler(budget_repository=budgets)


def get_update_budget_handler(
    budgets: BudgetRepository = Depends(get_budget_repository),
) -> UpdateBudgetHandler:
    return UpdateBudgetHandler(budget_repository=budgets)


def get_delete_budget_handler(
    budgets: BudgetRepository = Depends(get_budget_repository),
) -> DeleteBudgetHandler:
    return DeleteBudgetHandler(budget_repository=budgets)


def get_get_budget_overview_handler(
    session: AsyncSession = Depends(get_db_session),
    budgets: BudgetRepository = Depends(get_budget_repository),
) -> GetBudgetOverviewHandler:
    transaction_repository = SqlAlchemyTransactionRepository(session)
    return GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transaction_repository
    )


def get_get_spending_insights_handler(
    session: AsyncSession = Depends(get_db_session),
) -> GetSpendingInsightsHandler:
    transaction_repository = SqlAlchemyTransactionRepository(session)
    return GetSpendingInsightsHandler(transaction_repository=transaction_repository)


def get_alert_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AlertRepository:
    return SqlAlchemyAlertRepository(session)


def get_evaluate_alerts_for_transaction_handler(
    session: AsyncSession = Depends(get_db_session),
    alerts: AlertRepository = Depends(get_alert_repository),
    budgets: BudgetRepository = Depends(get_budget_repository),
) -> EvaluateAlertsForTransactionHandler:
    transaction_repository = SqlAlchemyTransactionRepository(session)
    return EvaluateAlertsForTransactionHandler(
        alert_repository=alerts,
        budget_repository=budgets,
        transaction_repository=transaction_repository,
    )


def get_dismiss_alert_handler(
    alerts: AlertRepository = Depends(get_alert_repository),
) -> DismissAlertHandler:
    return DismissAlertHandler(alert_repository=alerts)


def get_list_alerts_handler(
    alerts: AlertRepository = Depends(get_alert_repository),
) -> ListAlertsHandler:
    return ListAlertsHandler(alert_repository=alerts)


def get_subscription_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SubscriptionRepository:
    return SqlAlchemySubscriptionRepository(session)


def get_detect_subscriptions_for_transaction_handler(
    session: AsyncSession = Depends(get_db_session),
    subscriptions: SubscriptionRepository = Depends(get_subscription_repository),
) -> DetectSubscriptionsForTransactionHandler:
    transaction_repository = SqlAlchemyTransactionRepository(session)
    return DetectSubscriptionsForTransactionHandler(
        subscription_repository=subscriptions,
        transaction_repository=transaction_repository,
    )


def get_confirm_subscription_handler(
    subscriptions: SubscriptionRepository = Depends(get_subscription_repository),
) -> ConfirmSubscriptionHandler:
    return ConfirmSubscriptionHandler(subscription_repository=subscriptions)


def get_dismiss_subscription_handler(
    subscriptions: SubscriptionRepository = Depends(get_subscription_repository),
) -> DismissSubscriptionHandler:
    return DismissSubscriptionHandler(subscription_repository=subscriptions)


def get_mark_not_subscription_handler(
    subscriptions: SubscriptionRepository = Depends(get_subscription_repository),
) -> MarkNotSubscriptionHandler:
    return MarkNotSubscriptionHandler(subscription_repository=subscriptions)


def get_list_subscriptions_handler(
    subscriptions: SubscriptionRepository = Depends(get_subscription_repository),
) -> ListSubscriptionsHandler:
    return ListSubscriptionsHandler(subscription_repository=subscriptions)
