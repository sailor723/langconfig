import pandas as pd

df = pd.read_csv('/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-5/enterprise_data/modern_marketing.csv')
print("原始数据：")
print(df)

df.rename(columns={'market': 'Region'}, inplace=True)
df['price_per_unit'] = df['price_per_unit'].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False).astype(float)

print("\n清洗后数据：")
print(df)

df['total_revenue'] = df['qty'] * df['price_per_unit']
print("\n各交易收入：")
print(df[['tx_id', 'Region', 'prod_cat', 'qty', 'price_per_unit', 'total_revenue', 'rebate']])

tax_rates = {'EMEA': 0.15, 'US': 0.08, 'APAC': 0.12}

def calc_net(row):
    rate = tax_rates.get(row['Region'], 0.0)
    tax = row['total_revenue'] * rate
    return row['total_revenue'] - tax

df['net_income'] = df.apply(calc_net, axis=1)
print("\n净收入计算明细：")
print(df[['tx_id', 'Region', 'total_revenue', 'net_income']])

region_summary = df.groupby('Region').agg(
    交易笔数=('tx_id', 'count'),
    总收入=('total_revenue', 'sum'),
    净收入=('net_income', 'sum')
).reset_index()

region_summary['绩效状态'] = region_summary['总收入'].apply(
    lambda x: 'UNDER_PERFORMING' if x < 500 else '正常'
)

print("\n\n最终 Region 汇总：")
print(region_summary.to_string(index=False))
