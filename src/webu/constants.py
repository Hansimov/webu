from tclogger import norm_path

WEBU_LIB_ROOT = norm_path(__file__).parent
WEBU_SRC_ROOT = norm_path(__file__).parents[1]
WEBU_DATA_ROOT = WEBU_SRC_ROOT / "data"
