import joblib
import os
import numpy as np
import warnings
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

# Suppress sklearn warnings about feature names
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

class AIFraudDetector:
    """
    An AI-based fraud detection model using a Random Forest classifier
    """
    
    def __init__(self, model_path=None):
        """
        Initialize the AI detector with a pre-trained model or create a new one
        
        Args:
            model_path (str): Path to the pre-trained model file
        """
        self.model_path = model_path
        self.model = None
        self.scaler = None
        
        if model_path and os.path.exists(model_path):
            self.load_model()
        else:
            self.initialize_model()
    
    def initialize_model(self):
        """
        Initialize a new model
        """
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42
        )
        self.scaler = StandardScaler()
    
    def load_model(self):
        """
        Load a pre-trained model from disk
        """
        try:
            model_data = joblib.load(self.model_path)
            self.model = model_data["model"]
            self.scaler = model_data["scaler"]
        except Exception as e:
            print(f"Error loading model: {e}")
            self.initialize_model()
    
    def save_model(self, path=None):
        """
        Save the model to disk
        
        Args:
            path (str): Path to save the model
        """
        save_path = path or self.model_path
        if save_path:
            model_data = {
                "model": self.model,
                "scaler": self.scaler
            }
            joblib.dump(model_data, save_path)
    
    def preprocess_transaction(self, transaction):
        """
        Preprocess a transaction for the model
        
        Args:
            transaction (dict): The transaction data
            
        Returns:
            numpy.ndarray: Preprocessed features
        """
        # Extract features from the transaction
        features = [
            transaction["amount"],
            # One-hot encoding for payment_mode
            1 if transaction["payment_mode"] == "credit_card" else 0,
            1 if transaction["payment_mode"] == "debit_card" else 0,
            1 if transaction["payment_mode"] == "bank_transfer" else 0,
            1 if transaction["payment_mode"] == "digital_wallet" else 0,
            # One-hot encoding for channel
            1 if transaction["channel"] == "web" else 0,
            1 if transaction["channel"] == "mobile_app" else 0,
            1 if transaction["channel"] == "in_store" else 0,
            1 if transaction["channel"] == "phone" else 0,
            # Additional features to match the model's expected 13 features
            transaction.get("amount", 0) / 1000,  # Normalized amount
            len(transaction.get("payer_id", "")),  # Length of payer ID as a feature
            len(transaction.get("payee_id", "")),  # Length of payee ID as a feature
            1 if transaction.get("bank") else 0,  # Whether bank info is provided
        ]
        
        # Convert to numpy array
        features = np.array(features).reshape(1, -1)
        
        # Scale features if scaler is fitted
        if hasattr(self.scaler, 'mean_'):
            features = self.scaler.transform(features)
        
        return features
    
    def train(self, transactions, labels):
        """
        Train the model on a dataset
        
        Args:
            transactions (list): List of transaction dictionaries
            labels (list): List of fraud labels (1 for fraud, 0 for non-fraud)
        """
        # Preprocess all transactions
        features = np.vstack([self.preprocess_transaction(t) for t in transactions])
        
        # Fit the scaler
        self.scaler.fit(features)
        
        # Scale the features
        scaled_features = self.scaler.transform(features)
        
        # Train the model
        self.model.fit(scaled_features, labels)
    
    def predict(self, transaction):
        """
        Predict if a transaction is fraudulent
        
        Args:
            transaction (dict): The transaction data
            
        Returns:
            tuple: (is_fraudulent (bool), fraud_probability (float))
        """
        # If model is not trained, return a default prediction
        if self.model is None or not hasattr(self.model, 'classes_'):
            # Apply basic heuristics for large transactions when model isn't available
            amount = transaction.get("amount", 0)
            if amount > 50000:
                return True, 0.8
            elif amount > 25000:
                return True, 0.6
            elif amount > 10000:
                return False, 0.4
            return False, 0.09
        
        # Preprocess the transaction
        features = self.preprocess_transaction(transaction)
        
        # Get the probability of fraud
        probabilities = self.model.predict_proba(features)[0]
        fraud_probability = probabilities[1] if len(probabilities) > 1 else 0.0
        
        # Adjust probability based on transaction amount for more sensitivity
        amount = transaction.get("amount", 0)
        if amount > 50000:
            fraud_probability = max(fraud_probability, 0.8)
        elif amount > 25000:
            fraud_probability = max(fraud_probability, 0.6)
        elif amount > 10000:
            fraud_probability = max(fraud_probability, 0.4)
        
        # Predict fraud if probability exceeds threshold (0.5)
        is_fraudulent = fraud_probability >= 0.5
        
        return is_fraudulent, fraud_probability
