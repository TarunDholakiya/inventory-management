<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card">
      <div class="budget-control">
        <label class="budget-label" for="budget-slider">{{ t('restocking.budgetLabel') }}</label>
        <input
          id="budget-slider"
          type="range"
          min="1000"
          max="125000"
          step="1000"
          v-model.number="budget"
          class="budget-slider"
        />
        <span class="budget-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</span>
      </div>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ (recommendation?.total_cost || 0).toLocaleString() }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budgetLabel') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ (recommendation?.remaining_budget || 0).toLocaleString() }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }} ({{ items.length }})</h3>
          <button
            class="place-order-btn"
            :disabled="placing || items.length === 0"
            @click="placeOrder"
          >
            {{ placing ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="placeSuccess" class="success-message">{{ placeSuccess }}</div>
        <div v-if="placeError" class="error">{{ placeError }}</div>

        <div v-if="items.length === 0" class="empty-state">{{ t('restocking.noItemsAtBudget') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.sku">
                <td>{{ item.sku }}</td>
                <td>{{ translateProductName(item.name) }}</td>
                <td>{{ item.category }}</td>
                <td>{{ item.quantity }}</td>
                <td>{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                <td><strong>{{ currencySymbol }}{{ item.line_total.toLocaleString() }}</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

// Note: this view has no warehouse/category/status/month dimension, so it
// intentionally does not use useFilters() (same posture as Reports.vue).
export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const budget = ref(25000)
    const loading = ref(true)
    const error = ref(null)
    const recommendation = ref(null)

    const placing = ref(false)
    const placeError = ref(null)
    const placeSuccess = ref(null)

    const items = computed(() => recommendation.value?.items || [])

    const loadRecommendation = async () => {
      try {
        loading.value = true
        error.value = null
        recommendation.value = await api.getRestockRecommendation(budget.value)
      } catch (err) {
        error.value = 'Failed to load recommendation: ' + err.message
        recommendation.value = null
      } finally {
        loading.value = false
      }
    }

    // Debounce: the slider fires a change on every tick while dragging, so
    // wait for the value to settle before hitting the API.
    let debounceTimer = null
    watch(budget, () => {
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(loadRecommendation, 300)
    })

    const placeOrder = async () => {
      try {
        placing.value = true
        placeError.value = null
        placeSuccess.value = null
        const order = await api.placeRestockOrder(budget.value)
        placeSuccess.value = t('restocking.orderPlaced', {
          orderNumber: order.order_number,
          leadTime: t('orders.submittedOrders.leadTimeDays', { days: order.lead_time_days })
        })
        await loadRecommendation()
      } catch (err) {
        // Surface the backend's actual reason (e.g. "budget too low") rather than a generic axios message
        placeError.value = err.response?.data?.detail || t('restocking.orderFailed')
      } finally {
        placing.value = false
      }
    }

    onMounted(loadRecommendation)

    return {
      t,
      currencySymbol,
      translateProductName,
      budget,
      loading,
      error,
      recommendation,
      items,
      placing,
      placeError,
      placeSuccess,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-control {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}

.budget-slider {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  outline: none;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: 2px solid #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.budget-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: 2px solid #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.budget-value {
  min-width: 110px;
  text-align: right;
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
}

.place-order-btn {
  padding: 0.5rem 1.25rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #2563eb;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.success-message {
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #64748b;
  font-size: 0.938rem;
}
</style>
