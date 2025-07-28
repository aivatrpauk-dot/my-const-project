from aiogram.dispatcher.filters.state import State, StatesGroup

class AnalyticsStates(StatesGroup):
    waiting_for_article = State()
    waiting_for_price_and_cost = State()

class AnalyticsPeriodState(StatesGroup):
    waiting_for_period_type = State()
    waiting_for_period_size = State()
    waiting_for_date = State()
    waiting_for_confirmation = State()