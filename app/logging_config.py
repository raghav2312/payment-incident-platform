#The code here makes my payments apps logs appear as a structured JSON,
#with a request ID so you can identify which request produced each log.

import json
import logging                                                                      #Python's built in logging system. Lets you record messsages at different severity levels
from datetime import datetime, timezone

from app.middleware.request_context import request_id_context

# Part	Job
# Logger	Receives your logging calls and checks their severity
# Handler	Sends accepted logs somewhere, such as the console
# Formatter	Converts each log into the desired text format
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:                            #self: this particular formatter object; record: a LogRecord containing info about one logging event
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),                                        #record.getMessage(): combines the message template and the argument
            "request_id": request_id_context.get(),                                #reads the request.id from the current execution context (added by the middleware)
        }

        # Include these details when the logging call supplies them.
        for field in ("method", "path", "status_code", "duration_ms"):
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)

        # Include the traceback when the log record contains an exception.
        if record.exc_info:                                                         # Checks whether the log record contains exception details.
            log_entry["exception"] = self.formatException(record.exc_info)          #self.formatException(...) turns it into readable traceback showing the error and the code locations

        return json.dumps(log_entry)                                               #return the log_entry in the form of json string



#It performs the setup: gets the writer, sets the importance threshold, attaches the helper and formatter, and stops messages from being passed upstairs.
def configure_logging() -> None:
    logger = logging.getLogger("payment_platform")                                 #selects the logger name
    logger.setLevel(logging.INFO)                                                  #which msg are worth recording (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    # Avoid duplicate handlers if setup runs again.
    if not any(                                                                    #only run the code below if theresm no handler is not assigned
        handler.get_name() == "payment_platform_console"
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler()                                          #handler decides the next destination of the finished msg i.e where to write
        handler.set_name("payment_platform_console")                               #gives handler a name tag
        handler.setFormatter(JsonFormatter())                                      #use our json formatter before writing each msg
        logger.addHandler(handler)

    logger.propagate = False



# Python automatically collects information about the event into something called a record.

# Imagine this card:
# Time:     When the message was created
# Level:    INFO
# Writer:   payment_platform
# Message:  Payment created

# You don’t need to create this card yourself. Python’s logging system does it. And then the Formatter puts that record in the defined template