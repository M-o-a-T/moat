
#ifndef MOAT_SERIAL_MSG
#define MOAT_SERIAL_MSG

#include "moat/message.h"

/*
 * @brief Send a message to the device's serial connection.
 */
void send_serial_msg(BusMessage msg);

/*
 * @brief Send a message to the device's serial connection.
 */
void send_serial_str(char *msg);

/*
 * @brief Fetch a message from the device's serial connection.
 */
BusMessage recv_serial_msg(int blocking);

#endif // MOAT_SERIAL_MSG
