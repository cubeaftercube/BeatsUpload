import database
import file_processing
import telegram_module

if __name__ == '__main__':
    print("Hello, this is BeatsUpload!")
    database.init_db()
    print("База данных готова.")
    telegram_module.start_bot()
