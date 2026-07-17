export type PaymentMethod = 'COD' | 'Prepaid'
export type RiskLevel = 'High' | 'Medium' | 'Low'
export type OrderStatus = 'New' | 'Ready to book' | 'Booked' | 'In transit'

export interface Order {
  id: string
  date: string
  customer: string
  initials: string
  city: string
  state: string
  amount: number
  payment: PaymentMethod
  customerType: 'Repeat Customer' | 'New Customer'
  risk: RiskLevel
  courier: string
  status: OrderStatus
}

export const orders: Order[] = [
  ['MM-10482', '17 Jul, 2026', 'Aarav Mehta', 'AM', 'Mumbai', 'Maharashtra', 1249, 'Prepaid', 'Repeat Customer', 'Low', 'Delhivery', 'New'],
  ['MM-10481', '17 Jul, 2026', 'Sana Kapoor', 'SK', 'Bengaluru', 'Karnataka', 899, 'COD', 'New Customer', 'Medium', 'Blue Dart', 'Ready to book'],
  ['MM-10480', '17 Jul, 2026', 'Rohan Shah', 'RS', 'Ahmedabad', 'Gujarat', 2140, 'Prepaid', 'Repeat Customer', 'Low', 'Delhivery', 'Booked'],
  ['MM-10479', '16 Jul, 2026', 'Isha Nair', 'IN', 'Kochi', 'Kerala', 675, 'COD', 'New Customer', 'High', 'Ecom Express', 'New'],
  ['MM-10478', '16 Jul, 2026', 'Kabir Singh', 'KS', 'New Delhi', 'Delhi', 1599, 'Prepaid', 'Repeat Customer', 'Low', 'Blue Dart', 'In transit'],
  ['MM-10477', '16 Jul, 2026', 'Meera Iyer', 'MI', 'Chennai', 'Tamil Nadu', 1125, 'COD', 'New Customer', 'Medium', 'Xpressbees', 'Ready to book'],
  ['MM-10476', '15 Jul, 2026', 'Aditya Verma', 'AV', 'Lucknow', 'Uttar Pradesh', 780, 'COD', 'Repeat Customer', 'Low', 'Delhivery', 'Booked'],
  ['MM-10475', '15 Jul, 2026', 'Pooja Malhotra', 'PM', 'Gurugram', 'Haryana', 1890, 'Prepaid', 'Repeat Customer', 'Low', 'Blue Dart', 'In transit'],
  ['MM-10474', '15 Jul, 2026', 'Vikram Rao', 'VR', 'Hyderabad', 'Telangana', 940, 'COD', 'New Customer', 'High', 'Ecom Express', 'New'],
  ['MM-10473', '14 Jul, 2026', 'Nisha Gupta', 'NG', 'Jaipur', 'Rajasthan', 1349, 'Prepaid', 'New Customer', 'Medium', 'Delhivery', 'Ready to book'],
  ['MM-10472', '14 Jul, 2026', 'Arjun Menon', 'AM', 'Pune', 'Maharashtra', 2249, 'COD', 'Repeat Customer', 'Low', 'Blue Dart', 'Booked'],
  ['MM-10471', '14 Jul, 2026', 'Tanya Bhatia', 'TB', 'Noida', 'Uttar Pradesh', 560, 'COD', 'New Customer', 'Medium', 'Xpressbees', 'New'],
  ['MM-10470', '13 Jul, 2026', 'Karan Patel', 'KP', 'Surat', 'Gujarat', 1780, 'Prepaid', 'Repeat Customer', 'Low', 'Delhivery', 'In transit'],
  ['MM-10469', '13 Jul, 2026', 'Riya Chatterjee', 'RC', 'Kolkata', 'West Bengal', 825, 'COD', 'New Customer', 'High', 'Ecom Express', 'Ready to book'],
  ['MM-10468', '13 Jul, 2026', 'Dev Khanna', 'DK', 'Chandigarh', 'Chandigarh', 2499, 'Prepaid', 'Repeat Customer', 'Low', 'Blue Dart', 'Booked'],
  ['MM-10467', '12 Jul, 2026', 'Ananya Das', 'AD', 'Bhubaneswar', 'Odisha', 1099, 'COD', 'New Customer', 'Medium', 'Delhivery', 'New'],
  ['MM-10466', '12 Jul, 2026', 'Yash Kulkarni', 'YK', 'Nashik', 'Maharashtra', 1450, 'Prepaid', 'Repeat Customer', 'Low', 'Xpressbees', 'In transit'],
  ['MM-10465', '12 Jul, 2026', 'Simran Kaur', 'SK', 'Amritsar', 'Punjab', 720, 'COD', 'New Customer', 'High', 'Ecom Express', 'Ready to book'],
  ['MM-10464', '11 Jul, 2026', 'Neil Fernandes', 'NF', 'Goa', 'Goa', 1699, 'Prepaid', 'Repeat Customer', 'Low', 'Delhivery', 'Booked'],
  ['MM-10463', '11 Jul, 2026', 'Aditi Jain', 'AJ', 'Indore', 'Madhya Pradesh', 980, 'COD', 'New Customer', 'Medium', 'Blue Dart', 'New'],
  ['MM-10462', '11 Jul, 2026', 'Manav Sethi', 'MS', 'Dehradun', 'Uttarakhand', 1250, 'Prepaid', 'Repeat Customer', 'Low', 'Xpressbees', 'In transit'],
  ['MM-10461', '10 Jul, 2026', 'Sneha Reddy', 'SR', 'Visakhapatnam', 'Andhra Pradesh', 1150, 'COD', 'New Customer', 'Medium', 'Delhivery', 'Booked'],
  ['MM-10460', '10 Jul, 2026', 'Harsh Vardhan', 'HV', 'Patna', 'Bihar', 645, 'COD', 'New Customer', 'High', 'Ecom Express', 'Ready to book'],
  ['MM-10459', '10 Jul, 2026', 'Kavya Pillai', 'KP', 'Thiruvananthapuram', 'Kerala', 1380, 'Prepaid', 'Repeat Customer', 'Low', 'Blue Dart', 'In transit'],
  ['MM-10458', '09 Jul, 2026', 'Rahul Sinha', 'RS', 'Ranchi', 'Jharkhand', 845, 'COD', 'New Customer', 'Medium', 'Xpressbees', 'New'],
].map(([id, date, customer, initials, city, state, amount, payment, customerType, risk, courier, status]) => ({
  id: String(id),
  date: String(date),
  customer: String(customer),
  initials: String(initials),
  city: String(city),
  state: String(state),
  amount: Number(amount),
  payment: payment as PaymentMethod,
  customerType: customerType as Order['customerType'],
  risk: risk as RiskLevel,
  courier: String(courier),
  status: status as OrderStatus,
}))
