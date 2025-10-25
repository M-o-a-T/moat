set(IDF_TARGET esp32s3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    # boards/sdkconfig.s3
    ${MICROPY_BOARD_DIR}/sdkconfig.board
)
