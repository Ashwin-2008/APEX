try:
    import xgboost
    print("XGBOOST_AVAILABLE")
except ImportError:
    print("XGBOOST_NOT_AVAILABLE")
try:
    import sklearn
    print("SKLEARN", sklearn.__version__)
except ImportError:
    print("SKLEARN_NOT_AVAILABLE")
try:
    import numpy
    print("NUMPY", numpy.__version__)
except ImportError:
    print("NUMPY_NOT_AVAILABLE")