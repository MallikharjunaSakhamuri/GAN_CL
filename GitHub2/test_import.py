{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "8d92d599",
   "metadata": {},
   "outputs": [],
   "source": [
    "# test_import.py\n",
    "import sys\n",
    "print(\"Python path:\", sys.path)\n",
    "\n",
    "try:\n",
    "    import model_modules\n",
    "    print(\"Available items:\", dir(model_modules))\n",
    "except Exception as e:\n",
    "    print(\"Import error:\", e)# test_import.py\n",
    "import sys\n",
    "print(\"Python path:\", sys.path)\n",
    "\n",
    "try:\n",
    "    import model_modules\n",
    "    print(\"Available items:\", dir(model_modules))\n",
    "except Exception as e:\n",
    "    print(\"Import error:\", e)"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3 (ipykernel)",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.9.21"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
