from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import time
import concurrent.futures
from datetime import datetime
import json
from typing import Optional
import uuid

from ..database import crud, database, models
from ..models.combined_model import CombinedFraudDetector
from . import schemas
import os

# Create router
router = APIRouter()

# Initialize fraud detector with pre-trained model
model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                          "models", "trained", "fraud_model.pkl")
fraud_detector = CombinedFraudDetector(ai_model_path=model_path if os.path.exists(model_path) else None)

# Dependency to get the database session
def get_db():
    return next(database.get_db())

def process_transaction(transaction_dict, db):
    """
    Process a transaction and detect fraud
    
    Args:
        transaction_dict (dict): Transaction data
        db (Session): Database session
        
    Returns:
        tuple: (is_fraud, fraud_score, prediction_time_ms, transaction_id)
    """
    start_time = time.time()
    
    # Get all active custom rules
    custom_rules = crud.get_all_custom_rules(db, active_only=True)
    
    # Update fraud detector with custom rules
    fraud_detector.set_custom_rules(custom_rules)
    
    # Detect fraud with a lower threshold for high-value transactions
    threshold = 0.05 if transaction_dict.get("amount", 0) > 10000 else 0.5
    is_fraud, fraud_score, rule_score, ai_score, reasons = fraud_detector.detect_fraud(transaction_dict, threshold=threshold)
    
    # Calculate prediction time
    prediction_time_ms = int((time.time() - start_time) * 1000)
    
    # Store transaction in database
    try:
        # Convert additional_data to JSON string if it's a dict
        additional_data = transaction_dict.get("additional_data", {})
        if isinstance(additional_data, dict):
            additional_data_str = json.dumps(additional_data)
        else:
            additional_data_str = None
            
        # Create a new transaction record
        transaction = models.Transaction(
            transaction_id=transaction_dict["transaction_id"],
            amount=transaction_dict["amount"],
            payer_id=transaction_dict["payer_id"],
            payee_id=transaction_dict["payee_id"],
            payment_mode=transaction_dict["payment_mode"],
            channel=transaction_dict["channel"],
            bank=transaction_dict.get("bank"),
            additional_data=additional_data_str,
            is_fraud_predicted=is_fraud,
            fraud_score=fraud_score,
            prediction_time_ms=prediction_time_ms
        )
        
        # Add and commit
        db.add(transaction)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error storing transaction {transaction_dict['transaction_id']}: {str(e)}")
    
    return is_fraud, fraud_score, prediction_time_ms, transaction_dict["transaction_id"]

@router.post("/detect", response_model=schemas.TransactionResponse)
def detect_fraud(transaction: schemas.TransactionCreate, db: Session = Depends(get_db)):
    """
    Detect fraud for a single transaction
    
    Args:
        transaction (schemas.TransactionCreate): Transaction data
        db (Session): Database session
        
    Returns:
        schemas.TransactionResponse: Fraud detection result
    """
    # Convert Pydantic model to dict
    transaction_dict = transaction.dict()
    
    # Process transaction
    is_fraud, fraud_score, prediction_time_ms, transaction_id = process_transaction(transaction_dict, db)
    
    # Convert additional_data from string to dict if needed
    additional_data = transaction_dict.get("additional_data", {})
    if additional_data is None:
        additional_data = {}
    
    # Return response
    return schemas.TransactionResponse(
        transaction_id=transaction_id,
        amount=transaction_dict["amount"],
        payer_id=transaction_dict["payer_id"],
        payee_id=transaction_dict["payee_id"],
        payment_mode=transaction_dict["payment_mode"],
        channel=transaction_dict["channel"],
        bank=transaction_dict.get("bank"),
        additional_data=additional_data,
        is_fraud_predicted=is_fraud,
        fraud_score=fraud_score,
        prediction_time_ms=prediction_time_ms
    )

@router.post("/batch-detect", response_model=schemas.BatchTransactionResponse)
def batch_detect_fraud(batch_request: schemas.BatchTransactionRequest, db: Session = Depends(get_db)):
    """
    Batch fraud detection for multiple transactions
    """
    # Record start time
    start_time = time.time()
    
    # Process transactions in parallel
    results = {}
    
    def process_single_transaction(transaction):
        # Convert Pydantic model to dict
        transaction_dict = transaction.dict()
        
        # Process transaction
        is_fraud, fraud_score, prediction_time_ms, transaction_id = process_transaction(transaction_dict, db)
        
        # Create response
        response = schemas.TransactionResponse(
            transaction_id=transaction_id,
            amount=transaction_dict["amount"],
            payer_id=transaction_dict["payer_id"],
            payee_id=transaction_dict["payee_id"],
            payment_mode=transaction_dict["payment_mode"],
            channel=transaction_dict["channel"],
            bank=transaction_dict.get("bank"),
            additional_data=transaction_dict.get("additional_data", {}),
            is_fraud_predicted=is_fraud,
            fraud_score=fraud_score,
            prediction_time_ms=prediction_time_ms
        )
        
        return transaction_id, response
    
    # Use ThreadPoolExecutor to process transactions in parallel
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_single_transaction, tx) for tx in batch_request.transactions]
        for future in concurrent.futures.as_completed(futures):
            try:
                transaction_id, response = future.result()
                results[transaction_id] = response
            except Exception as e:
                print(f"Error processing transaction: {str(e)}")
    
    # Calculate total processing time
    total_time_ms = int((time.time() - start_time) * 1000)
    
    # Return batch response
    return schemas.BatchTransactionResponse(
        results=results,
        total_time_ms=total_time_ms
    )

@router.post("/report", response_model=schemas.FraudReportResponse)
def report_fraud(report: schemas.FraudReportCreate, db: Session = Depends(get_db)):
    """
    Report a fraudulent transaction
    """
    # Check if transaction exists
    transaction = crud.get_transaction_by_id(db, report.transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Check if fraud report already exists
    existing_report = crud.get_fraud_report_by_transaction_id(db, report.transaction_id)
    if existing_report:
        raise HTTPException(status_code=400, detail="Fraud report already exists for this transaction")
    
    # Create fraud report
    db_report = crud.create_fraud_report(db, report.dict())
    
    return schemas.FraudReportResponse(
        id=db_report.id,
        transaction_id=db_report.transaction_id,
        reporting_entity_id=db_report.reporting_entity_id,
        fraud_details=db_report.fraud_details,
        is_fraud_reported=db_report.is_fraud_reported,
        reported_at=db_report.reported_at
    )

@router.get("/transactions", response_model=List[schemas.TransactionResponse])
def get_transactions(
    limit: int = 100, 
    offset: int = 0,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    payment_mode: Optional[str] = None,
    channel: Optional[str] = None,
    is_fraud: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    Get a list of transactions with optional filtering
    
    Args:
        limit (int): Maximum number of transactions to return
        offset (int): Offset for pagination
        start_date (datetime): Filter by start date
        end_date (datetime): Filter by end date
        payment_mode (str): Filter by payment mode
        channel (str): Filter by channel
        is_fraud (bool): Filter by fraud status
        db (Session): Database session
        
    Returns:
        List[schemas.TransactionResponse]: List of transactions
    """
    try:
        # Query transactions with filters
        query = db.query(models.Transaction)
        
        if start_date:
            query = query.filter(models.Transaction.timestamp >= start_date)
        if end_date:
            query = query.filter(models.Transaction.timestamp <= end_date)
        if payment_mode:
            query = query.filter(models.Transaction.payment_mode == payment_mode)
        if channel:
            query = query.filter(models.Transaction.channel == channel)
        if is_fraud is not None:
            query = query.filter(models.Transaction.is_fraud_predicted == is_fraud)
        
        # Apply limit and offset
        transactions = query.order_by(models.Transaction.timestamp.desc()).offset(offset).limit(limit).all()
        
        # Convert to response models
        result = []
        for tx in transactions:
            try:
                # Parse additional_data from JSON string to dict
                additional_data = {}
                if tx.additional_data:
                    try:
                        additional_data = json.loads(tx.additional_data)
                    except:
                        additional_data = {}
                
                result.append(schemas.TransactionResponse(
                    transaction_id=tx.transaction_id,
                    amount=tx.amount,
                    payer_id=tx.payer_id,
                    payee_id=tx.payee_id,
                    payment_mode=tx.payment_mode,
                    channel=tx.channel,
                    bank=tx.bank,
                    additional_data=additional_data,
                    is_fraud_predicted=tx.is_fraud_predicted,
                    fraud_score=tx.fraud_score,
                    prediction_time_ms=tx.prediction_time_ms,
                    timestamp=tx.timestamp
                ))
            except Exception as e:
                print(f"Error converting transaction {tx.transaction_id}: {str(e)}")
        
        return result
    except Exception as e:
        print(f"Error retrieving transactions: {str(e)}")
        return []

@router.get("/reports", response_model=List[schemas.FraudReportResponse])
def get_fraud_reports(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Get fraud reports
    """
    reports = crud.get_fraud_reports(db, skip=skip, limit=limit)
    
    return [
        schemas.FraudReportResponse(
            id=r.id,
            transaction_id=r.transaction_id,
            reporting_entity_id=r.reporting_entity_id,
            fraud_details=r.fraud_details,
            is_fraud_reported=r.is_fraud_reported,
            reported_at=r.reported_at
        )
        for r in reports
    ]

@router.get("/metrics", response_model=schemas.MetricsResponse)
def get_metrics(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """
    Get fraud detection metrics
    """
    # Get metrics from database
    metrics = crud.get_metrics(db, start_date, end_date)
    
    # Return metrics response
    return schemas.MetricsResponse(
        confusion_matrix=metrics["confusion_matrix"],
        precision=metrics["precision"],
        recall=metrics["recall"],
        f1_score=metrics["f1_score"],
        total_transactions=metrics["total_transactions"],
        predicted_frauds=metrics["predicted_frauds"],
        reported_frauds=metrics["reported_frauds"]
    )

@router.post("/detect-json", response_model=schemas.DetailedFraudResponse)
def detect_fraud_json(transaction_input: schemas.JsonTransactionInput, db: Session = Depends(get_db)):
    """
    Detect fraud for a single transaction provided in JSON format
    
    Args:
        transaction_input (schemas.JsonTransactionInput): Transaction data in JSON format
        db (Session): Database session
        
    Returns:
        schemas.DetailedFraudResponse: Detailed fraud detection result
    """
    # Extract transaction data
    transaction_data = transaction_input.transaction_data
    
    # Ensure transaction_id exists
    if "transaction_id" not in transaction_data:
        transaction_data["transaction_id"] = str(uuid.uuid4())
    
    # Get all active custom rules
    custom_rules = crud.get_all_custom_rules(db, active_only=True)
    
    # Update fraud detector with custom rules
    fraud_detector.set_custom_rules(custom_rules)
    
    # Process transaction using the fraud detector
    start_time = time.time()
    threshold = 0.05 if transaction_data.get("amount", 0) > 10000 else 0.5
    is_fraud, combined_score, rule_score, ai_score, reasons = fraud_detector.detect_fraud(transaction_data, threshold=threshold)
    prediction_time_ms = int((time.time() - start_time) * 1000)
    
    # Determine fraud source and reason
    fraud_source = "model" if ai_score > rule_score else "rule"
    
    # Generate fraud reason based on source
    if fraud_source == "rule":
        if reasons and isinstance(reasons, dict) and "rule_reason" in reasons:
            fraud_reason = reasons["rule_reason"]
        elif reasons and isinstance(reasons, list) and len(reasons) > 0:
            fraud_reason = reasons[0]
        elif transaction_data.get("amount", 0) > fraud_detector.rule_detector.config["amount_threshold"]:
            fraud_reason = "High transaction amount"
        elif transaction_data.get("channel") in fraud_detector.rule_detector.config["high_risk_channels"]:
            fraud_reason = "High-risk channel"
        elif transaction_data.get("payment_mode") in fraud_detector.rule_detector.config["high_risk_payment_modes"]:
            fraud_reason = "High-risk payment mode"
        else:
            fraud_reason = "Multiple risk factors"
    else:
        # Generate meaningful AI model fraud reasons based on transaction characteristics
        amount = transaction_data.get("amount", 0)
        payment_mode = transaction_data.get("payment_mode", "")
        channel = transaction_data.get("channel", "")
        
        # Analyze specific risk factors that the AI model considers
        risk_factors = []
        
        # Amount-based risks
        if amount > 50000:
            risk_factors.append("extremely high transaction amount")
        elif amount > 25000:
            risk_factors.append("very high transaction amount")
        elif amount > 10000:
            risk_factors.append("high transaction amount")
        
        # Payment mode risks
        if payment_mode in ["digital_wallet", "bank_transfer"]:
            risk_factors.append("high-risk payment method")
        
        # Channel risks
        if channel in ["phone", "web"]:
            risk_factors.append("remote transaction channel")
        
        # ID pattern risks (short IDs can indicate fake accounts)
        payer_id = transaction_data.get("payer_id", "")
        payee_id = transaction_data.get("payee_id", "")
        if len(payer_id) <= 3 or len(payee_id) <= 3:
            risk_factors.append("suspicious account identifiers")
        
        # Missing bank info for large transactions
        if amount > 5000 and not transaction_data.get("bank"):
            risk_factors.append("missing bank verification for large amount")
        
        # Generate descriptive fraud reason
        if risk_factors:
            if len(risk_factors) == 1:
                fraud_reason = f"Suspicious transaction pattern: {risk_factors[0]}"
            elif len(risk_factors) == 2:
                fraud_reason = f"Multiple risk indicators: {risk_factors[0]} and {risk_factors[1]}"
            else:
                fraud_reason = f"Multiple risk indicators including {risk_factors[0]}, {risk_factors[1]} and {len(risk_factors)-2} other factor(s)"
        else:
            # Fallback for when AI detects fraud but no obvious rules apply
            if ai_score > 0.8:
                fraud_reason = "AI model detected highly suspicious transaction pattern"
            elif ai_score > 0.6:
                fraud_reason = "AI model identified moderate fraud risk indicators"
            else:
                fraud_reason = "AI model flagged transaction based on learned fraud patterns"
    
    # Store transaction in database if it contains required fields
    required_fields = ["amount", "payer_id", "payee_id", "payment_mode", "channel"]
    if all(field in transaction_data for field in required_fields):
        try:
            # Convert additional_data to JSON string if it's a dict
            additional_data = transaction_data.get("additional_data", {})
            if isinstance(additional_data, dict):
                additional_data_str = json.dumps(additional_data)
            else:
                additional_data_str = None
                
            # Create a new transaction record
            transaction = models.Transaction(
                transaction_id=transaction_data["transaction_id"],
                amount=transaction_data["amount"],
                payer_id=transaction_data["payer_id"],
                payee_id=transaction_data["payee_id"],
                payment_mode=transaction_data["payment_mode"],
                channel=transaction_data["channel"],
                bank=transaction_data.get("bank"),
                additional_data=additional_data_str,
                is_fraud_predicted=is_fraud,
                fraud_score=combined_score,
                prediction_time_ms=prediction_time_ms
            )
            
            # Add and commit
            db.add(transaction)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Error storing transaction {transaction_data['transaction_id']}: {str(e)}")
    
    # Return detailed response
    return schemas.DetailedFraudResponse(
        transaction_id=transaction_data["transaction_id"],
        is_fraud=is_fraud,
        fraud_source=fraud_source,
        fraud_reason=fraud_reason,
        fraud_score=combined_score
    )

# Custom Rules endpoints

@router.post("/rules", response_model=schemas.CustomRuleResponse)
def create_rule(rule: schemas.CustomRuleCreate, db: Session = Depends(get_db)):
    """
    Create a new custom rule
    """
    # Check if rule with this name already exists
    existing_rule = crud.get_custom_rule_by_name(db, rule.name)
    if existing_rule:
        raise HTTPException(status_code=400, detail="Rule with this name already exists")
    
    # Create the rule
    return crud.create_custom_rule(db, rule.dict())

@router.get("/rules", response_model=List[schemas.CustomRuleResponse])
def get_rules(skip: int = 0, limit: int = 100, active_only: bool = False, db: Session = Depends(get_db)):
    """
    Get all custom rules with optional filtering
    """
    return crud.get_all_custom_rules(db, skip=skip, limit=limit, active_only=active_only)

@router.get("/rules/{rule_id}", response_model=schemas.CustomRuleResponse)
def get_rule(rule_id: int, db: Session = Depends(get_db)):
    """
    Get a custom rule by ID
    """
    rule = crud.get_custom_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule

@router.put("/rules/{rule_id}", response_model=schemas.CustomRuleResponse)
def update_rule(rule_id: int, rule_update: schemas.CustomRuleUpdate, db: Session = Depends(get_db)):
    """
    Update an existing rule
    """
    # Check if rule exists
    existing_rule = crud.get_custom_rule(db, rule_id)
    if not existing_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # If name is being updated, check it doesn't conflict
    if rule_update.name and rule_update.name != existing_rule.name:
        name_exists = crud.get_custom_rule_by_name(db, rule_update.name)
        if name_exists:
            raise HTTPException(status_code=400, detail="Rule with this name already exists")
    
    # Update the rule
    updated_rule = crud.update_custom_rule(db, rule_id, rule_update.dict(exclude_unset=True))
    if not updated_rule:
        raise HTTPException(status_code=400, detail="Failed to update rule")
    
    return updated_rule

@router.delete("/rules/{rule_id}", response_model=bool)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    """
    Delete a custom rule
    """
    success = crud.delete_custom_rule(db, rule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    return success

@router.patch("/rules/{rule_id}/activate", response_model=schemas.CustomRuleResponse)
def activate_rule(rule_id: int, db: Session = Depends(get_db)):
    """
    Activate a custom rule
    """
    rule = crud.activate_deactivate_rule(db, rule_id, True)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule

@router.patch("/rules/{rule_id}/deactivate", response_model=schemas.CustomRuleResponse)
def deactivate_rule(rule_id: int, db: Session = Depends(get_db)):
    """
    Deactivate a custom rule
    """
    rule = crud.activate_deactivate_rule(db, rule_id, False)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule

@router.get("/transactions/count")
def get_transaction_count(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    payment_mode: Optional[str] = None,
    channel: Optional[str] = None,
    is_fraud: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    Get total count of transactions with optional filtering
    
    Returns:
        dict: Contains total_count and fraud_count
    """
    try:
        # Base query
        query = db.query(models.Transaction)
        
        # Apply filters
        if start_date:
            query = query.filter(models.Transaction.timestamp >= start_date)
        if end_date:
            query = query.filter(models.Transaction.timestamp <= end_date)
        if payment_mode:
            query = query.filter(models.Transaction.payment_mode == payment_mode)
        if channel:
            query = query.filter(models.Transaction.channel == channel)
        if is_fraud is not None:
            query = query.filter(models.Transaction.is_fraud_predicted == is_fraud)
        
        # Get total count
        total_count = query.count()
        
        # Get fraud count
        fraud_count = query.filter(models.Transaction.is_fraud_predicted == True).count()
        
        return {
            "total_count": total_count,
            "fraud_count": fraud_count,
            "legitimate_count": total_count - fraud_count
        }
    except Exception as e:
        print(f"Error getting transaction count: {str(e)}")
        return {
            "total_count": 0,
            "fraud_count": 0,
            "legitimate_count": 0
        }
