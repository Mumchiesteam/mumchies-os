import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { GeographyAnalytics } from './components/GeographyAnalytics'
import { sortGeographyRows, type GeographyData, type GeographyRow } from './services/analytics'

const row = (name: string, value: number): GeographyRow => ({ state: name, orders: value / 100, active_orders: value / 100, order_value: value, aov: 100, customers: value / 100, repeat_percent: 20, cod_percent: 60, prepaid_percent: 40, orders_change: 1, value_change: 100, aov_change: 2, repeat_points: 1 })
const data: GeographyData = { summary: { orders: 3, active_orders: 3, order_value: 300, aov: 100, customers: 3, repeat_percent: 20, cod_percent: 60, prepaid_percent: 40 }, comparisons: {}, states: [row('Karnataka', 200), row('Unknown', 100)], cities: { Karnataka: [{ ...row('', 200), state: undefined, city: 'Bengaluru' }] }, pincodes: { 'Karnataka|Bengaluru': [{ ...row('', 200), state: undefined, pincode: '560076' }] }, products: { all: [{ product: 'Makhana', orders: 2, quantity: 3, value: 200, order_percent: 66.7, repeat_orders: 1, order_change: 1, value_change: 100 }], 'state:Karnataka': [], 'city:Karnataka|Bengaluru': [] }, data_quality: { missing_state: 1, missing_city: 1, missing_pincode: 1 } }

describe('Geography Analytics', () => {
  it('renders KPIs, state drilldown entry, products and owner data quality', () => { const html = renderToStaticMarkup(<GeographyAnalytics data={data} showDataQuality />); for (const text of ['Geography Performance', 'State Performance', 'Karnataka', 'Unknown', 'Top Products in Selected Geography', 'Makhana', 'Missing State: 1']) expect(html).toContain(text) })
  it('sorts every numeric geography column without mutating input', () => { const sorted = sortGeographyRows(data.states, 'order_value', true); expect(sorted.map(value => value.state)).toEqual(['Karnataka', 'Unknown']); expect(data.states[0].state).toBe('Karnataka') })
  it('contains no operational orders endpoint dependency', async () => { const source = await import('./services/analytics'); expect(source.getAnalytics.toString()).not.toContain('/api/v1/orders') })
})
