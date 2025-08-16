import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objs as go
import requests
import json
import uuid
from datetime import datetime, timedelta
import os
import sys
import subprocess
import threading
import time

# Add the src directory to sys.path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# Configure the page
st.set_page_config(
    page_title="Fraud Detection Dashboard", 
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API configuration
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8001")
# Ensure API_BASE_URL has /api suffix
if not API_BASE_URL.endswith('/api'):
    API_BASE_URL = f"{API_BASE_URL.rstrip('/')}/api"
    
TRANSACTIONS_URL = f"{API_BASE_URL}/transactions"
TRANSACTIONS_COUNT_URL = f"{API_BASE_URL}/transactions/count"
METRICS_URL = f"{API_BASE_URL}/metrics"
RULES_URL = f"{API_BASE_URL}/rules"

# Session state initialization
if 'transactions_data' not in st.session_state:
    st.session_state.transactions_data = []
if 'api_running' not in st.session_state:
    st.session_state.api_running = False
if 'api_process' not in st.session_state:
    st.session_state.api_process = None
if 'latest_transaction' not in st.session_state:
    st.session_state.latest_transaction = None

def start_api_server():
    """Start the API server in background"""
    if not st.session_state.api_process or st.session_state.api_process.poll() is not None:
        try:
            # Start the API server
            st.session_state.api_process = subprocess.Popen(
                [sys.executable, "src/api/main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd()
            )
            # Give it a moment to start
            time.sleep(1)
            return True
        except Exception as e:
            st.error(f"Failed to start API server: {str(e)}")
            return False
    return True

# Helper functions
def fetch_transactions(limit=1000, offset=0, **filters):
    """Fetch transactions from API"""
    params = {"limit": limit, "offset": offset, **filters}
    # Add timestamp to prevent caching
    params["_t"] = int(time.time())
    try:
        response = requests.get(TRANSACTIONS_URL, params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Error fetching transactions: {response.status_code}")
            return []
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {str(e)}")
        return []

def fetch_transaction_counts(**filters):
    """Fetch real transaction counts from API"""
    params = {**filters}
    # Add timestamp to prevent caching
    params["_t"] = int(time.time())
    try:
        response = requests.get(TRANSACTIONS_COUNT_URL, params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {"total_count": 0, "fraud_count": 0, "legitimate_count": 0}
    except requests.exceptions.RequestException as e:
        return {"total_count": 0, "fraud_count": 0, "legitimate_count": 0}

def fetch_metrics(start_date=None, end_date=None):
    """Fetch metrics from API"""
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
        
    try:
        response = requests.get(METRICS_URL, params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return default_metrics()
    except requests.exceptions.RequestException as e:
        return default_metrics()

def default_metrics():
    return {
        "confusion_matrix": {"true_positives": 0, "false_positives": 0, "true_negatives": 0, "false_negatives": 0},
        "precision": 0,
        "recall": 0,
        "f1_score": 0,
        "total_transactions": 0,
        "predicted_frauds": 0,
        "reported_frauds": 0
    }

def check_api_status():
    """Check if API is running"""
    try:
        response = requests.get(f"{API_BASE_URL.replace('/api', '')}/health", timeout=2)
        return response.status_code == 200
    except:
        return False

def submit_transaction_to_api(transaction_data):
    """Submit transaction to API"""
    try:
        response = requests.post(f"{API_BASE_URL}/detect-json", 
                               json={"transaction_data": transaction_data}, 
                               timeout=10)
        if response.status_code == 200:
            return response.json(), None
        else:
            return None, f"API Error: {response.status_code} - {response.text}"
    except requests.exceptions.RequestException as e:
        return None, f"Connection Error: {str(e)}"

# Main app layout
st.title("🛡️ Fraud Detection, Alert, and Monitoring System")
st.info("🔗 **Backend API Access:** To connect with the backend API directly, visit https://fraud-detection-net.onrender.com")
st.markdown("---")

# Check API status
api_status = check_api_status()
if api_status:
    st.success("✅ API is running")
    st.session_state.api_running = True
else:
    st.session_state.api_running = False
    
    # Show manual start instructions
    st.error("🔧 **API Server Required**")
    st.markdown("""
    **To start the fraud detection system:**
    
    1. **Option 1 - Manual Start** (Recommended):
       ```bash
       python src/api/main.py
       ```
    
    2. **Option 2 - Auto Start**: 
    """)
    
    if st.button("🚀 Start API Server", type="primary"):
        with st.spinner("Starting API server..."):
            if start_api_server():
                st.success("✅ API server starting... Please refresh the page in a few seconds.")
                time.sleep(2)
                st.rerun()
            else:
                st.error("❌ Failed to start API server. Please start manually.")

# Sidebar for controls and forms
with st.sidebar:
    st.header("⚙️ Controls")
    
    # Auto-refresh option
    auto_refresh = st.checkbox("Auto-refresh data", value=False)
    if auto_refresh:
        refresh_interval = st.slider("Refresh interval (seconds)", 5, 60, 30)
    
    # Refresh controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Refresh Data", type="primary"):
            # Clear any cached data and refresh
            st.session_state.latest_transaction = None
            st.rerun()
    
    with col2:
        auto_refresh_enabled = st.checkbox("Auto-refresh (30s)", value=False)
    
    # Display last refresh time
    current_time = datetime.now().strftime("%H:%M:%S")
    st.caption(f"Last updated: {current_time}")
    
    st.markdown("---")
    
    # Data filters
    st.subheader("🔍 Filters")
    
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", datetime.now() - timedelta(days=30))
    with col2:
        end_date = st.date_input("End Date", datetime.now())
    
    payment_mode = st.selectbox("Payment Mode", 
                               ["All", "credit_card", "debit_card", "bank_transfer", "wallet", "upi"],
                               index=0)
    
    channel = st.selectbox("Channel", 
                          ["All", "web", "mobile_app", "pos", "atm", "branch"],
                          index=0)
    
    fraud_status = st.selectbox("Fraud Status", 
                               ["All", "Fraudulent", "Legitimate"],
                               index=0)
    
    st.markdown("---")
    
    # Transaction submission form
    st.subheader("➕ Add New Transaction")
    
    with st.form("new_transaction_form"):
        amount = st.number_input("Amount ($)", min_value=0.01, value=100.0, step=0.01)
        payer_id = st.text_input("Payer ID", placeholder="P12345")
        payee_id = st.text_input("Payee ID", placeholder="M67890")
        payment_mode_input = st.selectbox("Payment Mode", 
                                        ["credit_card", "debit_card", "bank_transfer", "wallet", "upi"])
        channel_input = st.selectbox("Channel", 
                                   ["web", "mobile_app", "pos", "atm", "branch"])
        bank = st.text_input("Bank (Optional)", placeholder="Chase")
        
        submitted = st.form_submit_button("Submit Transaction", type="primary")
        
        if submitted and st.session_state.api_running:
            if amount and payer_id and payee_id:
                # Create transaction data
                transaction_data = {
                    "transaction_id": str(uuid.uuid4()),
                    "amount": float(amount),
                    "payer_id": payer_id,
                    "payee_id": payee_id,
                    "payment_mode": payment_mode_input,
                    "channel": channel_input,
                    "bank": bank if bank else None,
                    "additional_data": {
                        "ip_address": "127.0.0.1",
                        "user_agent": "Streamlit",
                        "device_id": "STREAMLIT_DEVICE",
                        "location": "Dashboard",
                        "time_of_day": "day" if 6 <= datetime.now().hour < 18 else "night"
                    }
                }
                
                result, error = submit_transaction_to_api(transaction_data)
                
                if result:
                    # Store the latest transaction for highlighting
                    st.session_state.latest_transaction = result.get('transaction_id')
                    
                    # Display success message with fraud detection result
                    fraud_status = "🚨 FRAUDULENT" if result.get('is_fraud_predicted') else "✅ LEGITIMATE"
                    fraud_score = result.get('fraud_score', 0)
                    
                    st.success(f"✅ Transaction submitted successfully!")
                    
                    # Create an expander for detailed results
                    with st.expander("🔍 Fraud Detection Results", expanded=True):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Status", fraud_status)
                        with col2:
                            st.metric("Fraud Score", f"{fraud_score:.3f}")
                        with col3:
                            st.metric("Processing Time", f"{result.get('prediction_time_ms', 0)}ms")
                        
                        # Show detailed result
                        st.json(result)
                    
                    st.rerun()
                elif error:
                    st.error(f"❌ {error}")
            else:
                st.error("Please fill all required fields")
        elif submitted and not st.session_state.api_running:
            st.error("API is not running. Please start the API server first.")
    
    st.markdown("---")
    
    # JSON transaction submission
    st.subheader("📝 JSON Transaction")
    
    json_input = st.text_area("Transaction JSON", 
                             placeholder='''{
  "amount": 1000,
  "payer_id": "P12345",
  "payee_id": "M67890",
  "payment_mode": "credit_card",
  "channel": "web"
}''', height=150)
    
    if st.button("Process JSON Transaction") and st.session_state.api_running:
        try:
            transaction_data = json.loads(json_input)
            if "transaction_id" not in transaction_data:
                transaction_data["transaction_id"] = str(uuid.uuid4())
            
            result, error = submit_transaction_to_api(transaction_data)
            
            if result:
                # Store the latest transaction for highlighting
                # JSON endpoint might return transaction_id differently
                transaction_id = result.get('transaction_id') or transaction_data.get('transaction_id')
                st.session_state.latest_transaction = transaction_id
                
                # Display success message with fraud detection result
                # Note: JSON endpoint returns 'is_fraud' while regular endpoint returns 'is_fraud_predicted'
                is_fraud = result.get('is_fraud', result.get('is_fraud_predicted', False))
                fraud_status = "🚨 FRAUDULENT" if is_fraud else "✅ LEGITIMATE"
                fraud_score = result.get('fraud_score', 0)
                
                st.success(f"✅ JSON Transaction processed successfully!")
                
                # Show results in a simple container instead of expander to avoid blur
                st.markdown("### 🔍 Fraud Detection Results")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Status", fraud_status)
                with col2:
                    st.metric("Fraud Score", f"{fraud_score:.3f}")
                with col3:
                    processing_time = result.get('prediction_time_ms', 0)
                    if processing_time == 0:  # JSON endpoint might not have this field
                        st.metric("Source", result.get('fraud_source', 'N/A'))
                    else:
                        st.metric("Processing Time", f"{processing_time}ms")
                
                # Show detailed result in a collapsible section
                with st.expander("📄 Detailed Response", expanded=False):
                    st.json(result)
                
                # Add a small delay to let the user see the results before refreshing
                time.sleep(0.5)
                st.rerun()
            elif error:
                st.error(f"❌ {error}")
                
        except json.JSONDecodeError:
            st.error("❌ Invalid JSON format")

# Main dashboard content
if st.session_state.api_running:
    # Fetch data based on filters (temporarily removing date filters to fix API issue)
    filters = {"limit": 1000, "offset": 0}
    # TODO: Fix date filter format in API
    # if start_date:
    #     filters["start_date"] = start_date.isoformat()
    # if end_date:
    #     filters["end_date"] = end_date.isoformat()
    if payment_mode and payment_mode != "All":
        filters["payment_mode"] = payment_mode
    if channel and channel != "All":
        filters["channel"] = channel
    if fraud_status and fraud_status != "All":
        filters["is_fraud"] = "true" if fraud_status == "Fraudulent" else "false"
    
    # Always fetch fresh data
    transactions = fetch_transactions(**filters)
    
    # Get real transaction counts from database (not limited by pagination)
    count_filters = {}
    if payment_mode and payment_mode != "All":
        count_filters["payment_mode"] = payment_mode
    if channel and channel != "All":
        count_filters["channel"] = channel
    if fraud_status and fraud_status != "All":
        count_filters["is_fraud"] = "true" if fraud_status == "Fraudulent" else "false"
    
    real_counts = fetch_transaction_counts(**count_filters)
    metrics = fetch_metrics()
    
    # Use real database counts for metrics
    total_transactions = real_counts.get("total_count", 0)
    predicted_frauds = real_counts.get("fraud_count", 0)
    fraud_rate = (predicted_frauds / total_transactions * 100) if total_transactions > 0 else 0
    
    # Calculate average fraud score from displayed transactions
    if transactions:
        avg_fraud_score = sum(t.get('fraud_score', 0) for t in transactions) / len(transactions)
    else:
        avg_fraud_score = 0
    
    # Metrics cards with real-time data
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Transactions", 
            f"{total_transactions:,}",
            delta=f"+{1 if st.session_state.latest_transaction else 0}" if st.session_state.latest_transaction else None
        )
    
    with col2:
        st.metric(
            "Predicted Frauds", 
            f"{predicted_frauds:,}",
            delta=f"{fraud_rate:.1f}%" if fraud_rate > 0 else "0%"
        )
    
    with col3:
        st.metric(
            "Fraud Rate", 
            f"{fraud_rate:.1f}%",
            delta=f"{'High' if fraud_rate > 50 else 'Low'}" if fraud_rate > 0 else "None"
        )
    
    with col4:
        st.metric(
            "Avg Fraud Score", 
            f"{avg_fraud_score:.3f}",
            delta=f"{'High Risk' if avg_fraud_score > 0.5 else 'Low Risk'}" if avg_fraud_score > 0 else "No Risk"
        )
    
    # Charts
    if transactions:
        df = pd.DataFrame(transactions)
        
        # Charts row 1
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Fraud by Payment Mode")
            if 'payment_mode' in df.columns and 'is_fraud_predicted' in df.columns:
                payment_counts = df.groupby(['payment_mode', 'is_fraud_predicted']).size().reset_index(name='count')
                fig = px.bar(payment_counts, x='payment_mode', y='count', 
                           color='is_fraud_predicted', barmode='group',
                           color_discrete_map={True: 'red', False: 'green'})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data available")
        
        with col2:
            st.subheader("📊 Fraud by Channel")
            if 'channel' in df.columns and 'is_fraud_predicted' in df.columns:
                channel_counts = df.groupby(['channel', 'is_fraud_predicted']).size().reset_index(name='count')
                fig = px.bar(channel_counts, x='channel', y='count', 
                           color='is_fraud_predicted', barmode='group',
                           color_discrete_map={True: 'red', False: 'green'})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data available")
        
        # Charts row 2
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🎯 Confusion Matrix")
            cm = metrics.get("confusion_matrix", {})
            confusion_data = [
                [cm.get("true_positives", 0), cm.get("false_negatives", 0)],
                [cm.get("false_positives", 0), cm.get("true_negatives", 0)]
            ]
            fig = px.imshow(confusion_data, 
                          x=["Predicted Fraud", "Predicted Not Fraud"],
                          y=["Actual Fraud", "Actual Not Fraud"],
                          color_continuous_scale="RdBu_r",
                          text_auto=True)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("💰 Amount Distribution")
            if 'amount' in df.columns and 'is_fraud_predicted' in df.columns:
                fig = px.histogram(df, x='amount', color='is_fraud_predicted',
                                 nbins=20, color_discrete_map={True: 'red', False: 'green'})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data available")
        
        # Transaction table
        st.subheader("📋 Transaction Data")
        
        # Search functionality
        search_term = st.text_input("🔍 Search transactions...", placeholder="Enter search term")
        
        # Filter data based on search
        display_df = df.copy()
        if search_term:
            mask = df.astype(str).apply(lambda x: x.str.contains(search_term, case=False, na=False)).any(axis=1)
            display_df = df[mask]
        
        # Format the dataframe for display
        if not display_df.empty:
            # Select and rename columns for better display
            display_columns = ['transaction_id', 'amount', 'payer_id', 'payee_id', 
                             'payment_mode', 'channel', 'bank', 'is_fraud_predicted', 
                             'fraud_score', 'timestamp']
            
            # Only include columns that exist in the dataframe
            available_columns = [col for col in display_columns if col in display_df.columns]
            table_df = display_df[available_columns].copy()
            
            # Rename columns for better readability
            column_renames = {
                'transaction_id': 'Transaction ID',
                'amount': 'Amount',
                'payer_id': 'Payer ID',
                'payee_id': 'Payee ID',
                'payment_mode': 'Payment Mode',
                'channel': 'Channel',
                'bank': 'Bank',
                'is_fraud_predicted': 'Fraud Status',
                'fraud_score': 'Fraud Score',
                'timestamp': 'Timestamp'
            }
            table_df = table_df.rename(columns=column_renames)
            
            # Format columns for better display
            if 'Amount' in table_df.columns:
                table_df['Amount'] = table_df['Amount'].apply(lambda x: f"${x:,.2f}")
            
            if 'Fraud Score' in table_df.columns:
                table_df['Fraud Score'] = table_df['Fraud Score'].apply(lambda x: f"{x:.3f}")
            
            if 'Fraud Status' in table_df.columns:
                table_df['Fraud Status'] = table_df['Fraud Status'].apply(
                    lambda x: "🚨 FRAUD" if x else "✅ LEGIT"
                )
            
            if 'Timestamp' in table_df.columns:
                table_df['Timestamp'] = pd.to_datetime(table_df['Timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Truncate long IDs for better display
            if 'Transaction ID' in table_df.columns:
                table_df['Transaction ID'] = table_df['Transaction ID'].apply(
                    lambda x: f"{str(x)[:8]}..." if len(str(x)) > 8 else str(x)
                )
            
            # Style the dataframe
            def highlight_rows(row):
                styles = []
                for _ in range(len(row)):
                    # Check if this is the latest transaction (need to check original ID)
                    original_id = display_df.iloc[row.name]['transaction_id'] if 'transaction_id' in display_df.columns else None
                    if st.session_state.latest_transaction and original_id == st.session_state.latest_transaction:
                        styles.append('background-color: #fff3cd; border: 2px solid #ffc107; font-weight: bold; color: #856404;')
                    # Check if it's fraudulent
                    elif 'Fraud Status' in row and "FRAUD" in str(row['Fraud Status']):
                        styles.append('background-color: #ffebee; color: #c62828; font-weight: 500;')
                    # Legitimate transaction
                    else:
                        styles.append('background-color: #e8f5e8; color: #2e7d32; font-weight: 500;')
                return styles
            
            # Apply styling and display
            styled_df = table_df.style.apply(highlight_rows, axis=1)
            
            # Show table with better configuration
            st.dataframe(
                styled_df, 
                use_container_width=True,
                height=400,  # Fixed height for better visibility
                hide_index=True  # Hide row indices
            )
            
            # Show table info
            col1, col2, col3 = st.columns(3)
            with col1:
                st.caption(f"📊 Showing {len(table_df)} of {total_transactions} total transactions")
            with col2:
                if st.session_state.latest_transaction:
                    if st.button("Clear Highlight", type="secondary"):
                        st.session_state.latest_transaction = None
                        st.rerun()
            with col3:
                st.caption("🟡 Recent | 🔴 Fraud | 🟢 Legitimate")
        else:
            st.info("No transactions found matching your criteria.")
    
    else:
        st.info("No transaction data available. Try submitting some transactions using the form in the sidebar.")

else:
    # Show instructions when API is not running
    st.error("🔧 **Setup Required**")
    st.markdown("""
    To use this dashboard, you need to start the API server:
    
    1. Open a new terminal
    2. Navigate to this project directory
    3. Run: `python src/api/main.py`
    4. The API will start on http://localhost:8001
    5. Refresh this page
    
    You can also initialize the database by running: `python init_db.py`
    """)

# Simple auto refresh mechanism
if 'auto_refresh_enabled' in locals() and auto_refresh_enabled and st.session_state.api_running:
    # Use JavaScript to refresh the page every 30 seconds
    st.markdown("""
    <script>
    setTimeout(function(){
        window.location.reload();
    }, 30000);
    </script>
    """, unsafe_allow_html=True)