import csv
import json
from pathlib import Path

import numpy as np
from scipy.integrate import odeint
from tqdm.auto import tqdm
import logging
import pandas as pd
from typing import List, Dict, Any


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')


from SentimentFlow.senti_keywords import keywords_example
class SentimentFlowCalculator:
    def __init__(self):
        """
        Initialize the SentimentFlowCalculator.

        Args:
            keywords (List[str]): List of keywords.
        """
        self.keywords = keywords_example

    @staticmethod
    def _calculate_sentiment_density(sentiment_scores: np.ndarray) -> float:
        """
        Calculate the sentiment density.

        Args:
            sentiment_scores (np.ndarray): Array of sentiment scores.

        Returns:
            float: Sentiment density.
        """
        return np.sum(np.abs(sentiment_scores))

    def _calculate_sentiment_pressure(self, score: float, text: str) -> float:
        """
        Calculate the sentiment pressure.

        Args:
            score (float): Sentiment score.
            text (str): Input text.

        Returns:
            float: Sentiment pressure.
        """
        pressure = 0
        if any(keyword.lower() in text.lower() for keyword in self.keywords):
            pressure += score
        return pressure

    @staticmethod
    def _calculate_sentiment_viscosity(sentiment_scores: np.ndarray) -> float:
        """
        Calculate the sentiment viscosity.

        Args:
            sentiment_scores (np.ndarray): Array of sentiment scores.

        Returns:
            float: Sentiment viscosity.
        """
        return np.std(sentiment_scores)

    @staticmethod
    def _calculate_external_contextual_force(polarity: float) -> float:
        """
        Calculate the external contextual force.

        Args:
            polarity (float): Polarity value.

        Returns:
            float: External contextual force.
        """
        return polarity

    @staticmethod
    def _navier_stokes_sentiment_flow(rho_sent: float, p_sent: np.ndarray, nu_sent: float, g_context: float, s: np.ndarray) -> np.ndarray:
        """
        Calculate the Navier-Stokes sentiment flow.

        Args:
            rho_sent (float): Sentiment density.
            p_sent (np.ndarray): Sentiment pressure.
            nu_sent (float): Sentiment viscosity.
            g_context (float): External contextual force.
            s (np.ndarray): Sentiment state.

        Returns:
            np.ndarray: Sentiment flow.
        """
        if rho_sent == 0:
            pressure_term = np.zeros_like(s)
        else:
            pressure_term = -1 / rho_sent * np.gradient(p_sent)

        grad_s = np.gradient(s)
        laplacian_s = np.gradient(grad_s)

        if np.any(np.isnan(s)) or np.any(np.isinf(s)) or np.any(np.isnan(grad_s)) or np.any(np.isinf(grad_s)):
            logging.warning("Warning: NaN or inf detected in s or grad_s. Skipping this iteration.")
            return None

        convective_term = s * grad_s
        viscous_term = nu_sent * laplacian_s

        rhs = convective_term + pressure_term + viscous_term + g_context
        np.clip(rhs, -1e10, 1e10, out=rhs)

        if np.any(np.isnan(rhs)) or np.any(np.isinf(rhs)):
            logging.warning("Warning: NaN or inf detected in rhs. Skipping this iteration.")
            return None

        return rhs

    @staticmethod
    def _differential_equation(s: np.ndarray, t: float, speech_info: List[Any]) -> np.ndarray:
        """
        Differential equation for sentiment flow.

        Args:
            s (np.ndarray): Sentiment state.
            t (float): Time.
            speech_info (List[Any]): List containing sentiment density, pressure, viscosity, and contextual force.

        Returns:
            np.ndarray: Derivative of sentiment state.
        """
        rho_sent, p_sent, nu_sent, g_context = speech_info
        dsdt = SentimentFlowCalculator._navier_stokes_sentiment_flow(rho_sent, p_sent, nu_sent, g_context, s)

        if dsdt is None:
            raise ValueError("Invalid sentiment flow calculation")

        return dsdt

    def calculate_navier_stocker_for_speeches(self, data: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        """
        Calculate the Navier-Stokes sentiment flow for each speech in a DataFrame.

        Args:
            data (pd.DataFrame): DataFrame containing 'title', 'speaker', 'speech', and emotion columns.

        Returns:
            Dict[str, List[Dict[str, Any]]]: Dictionary with simulation results.
        """
        all_s = {}
        sentiment_columns = data.columns.difference(['title', 'speaker', 'speech', 'POLARITY'])

        logging.info("Starting to calculate Navier-Stocker ...")
        for speaker in tqdm(data['speaker'].unique(),total=len(data['speaker']), desc="Calculating Navier-Stocker for speeches"):
            speaker_data = data[data['speaker'] == speaker]
            title = speaker_data.iloc[0]['title']
            initial_speaker = speaker_data.iloc[0]
            s0 = initial_speaker[sentiment_columns].apply(pd.to_numeric, errors='coerce').fillna(0).to_numpy()
            s0_g_context = self._calculate_external_contextual_force(initial_speaker['POLARITY'])
            initial_speech = initial_speaker['speech']
            current_time = 0
            all_results = []
            unique_all_results = []

            for i in range(1, len(speaker_data)):
                current_speech_data = speaker_data.iloc[i]
                if i == 1:
                    g_context = s0_g_context
                    current_speech = initial_speech
                else:
                    g_context = self._calculate_external_contextual_force(current_speech_data['POLARITY'])
                    current_speech = current_speech_data['speech']

                t = np.array([current_time, current_time + 1])
                speech_info = (
                    self._calculate_sentiment_density(s0),
                    np.array([self._calculate_sentiment_pressure(score, current_speech) for score in s0]),
                    self._calculate_sentiment_viscosity(s0),
                    g_context
                )
                s = odeint(self._differential_equation, s0, t, args=(speech_info,))

                for sim_result in s.tolist():
                    all_results.append((sim_result, current_speech))

                s0 = s[-1]
                current_time += 1

            simulation_results, speeches = zip(*unique_all_results) if unique_all_results else ([], [])
            simulation_results = np.vstack(simulation_results) if simulation_results else np.array([])

            if title not in all_s:
                all_s[title] = []
            all_s[title].append({
                'speaker': speaker,
                'speech': speeches,
                'simulation': simulation_results,
                'emotion dimension': sentiment_columns
            })
        logging.info("Finished calculating speeches.")
        logging.info(f"Processed {len(all_s)} speeches.")

        # Debug: Save the results to a CSV for inspection
        logging.info("Saving results to results/navier_stocker_speeches_results.json")
        Path("results/navier_stocker_speeches_results.json").parent.mkdir(parents=True, exist_ok=True)
        processed_df = pd.DataFrame(all_s)
        # Save the DataFrame to a JSON file
        json_file_path = 'results/navier_stocker_text_results.json'
        processed_df.to_json(json_file_path, orient='records', lines=True, indent=4)
        #all_s_df = pd.DataFrame.from_dict(all_s, orient='index')
        #all_s_df.to_csv('results/navier_stocker_speeches_results.csv', index=False)
        return all_s

    def calculate_navier_stocker_for_texts(self, data: pd.DataFrame) -> Dict[int, List[Dict[str, Any]]]:
        """
        Calculate the Navier-Stokes sentiment flow for each text in a DataFrame with 'text' and emotion columns.

        Args:
            data (pd.DataFrame): DataFrame containing 'text' and emotion columns.

        Returns:
            Dict[int, List[Dict[str, Any]]]: Dictionary with simulation results.
        """
        all_s = {}
        sentiment_columns = data.columns.difference(['text'])
        logging.info("Starting to calculate Navier-Stocker...")
        for idx, text_row in tqdm(data.iterrows(), total=data.shape[0], desc="Calculating Navier-Stocker for texts"):
            text = text_row['text']
            s0 = text_row[sentiment_columns].apply(pd.to_numeric, errors='coerce').fillna(0).to_numpy()
            s0_g_context = self._calculate_external_contextual_force(text_row['POLARITY'])
            current_time = 0
            all_results = []

            # Debug: Print initial values
            #print(f"Processing text index {idx}, Initial s0: {s0}, Initial g_context: {s0_g_context}")

            # Since we are processing single texts, there will be only one iteration
            current_text_row = text_row
            g_context = self._calculate_external_contextual_force(current_text_row['POLARITY'])

            t = np.array([current_time, current_time + 1])
            speech_info = (
                self._calculate_sentiment_density(s0),
                np.array([self._calculate_sentiment_pressure(score, text) for score in s0]),
                self._calculate_sentiment_viscosity(s0),
                g_context
            )
            s = odeint(self._differential_equation, s0, t, args=(speech_info,))

            all_results.extend((sim_result, text) for sim_result in s.tolist())
            s0 = s[-1]
            current_time += 1

            # Debug: Print intermediate results
            #print(f"Iteration 1, s0: {s0}, g_context: {g_context}, Text: {text}")

            if all_results:
                simulation_results, texts = zip(*all_results)
                simulation_results = np.vstack(simulation_results)
            else:
                simulation_results, texts = [], []

            if idx not in all_s:
                all_s[idx] = []
            all_s[idx].append({
                'text': texts,
                'simulation': simulation_results,
                'emotion dimension': sentiment_columns
            })

        logging.info("Finished calculating texts.")
        logging.info(f"Processed {len(all_s)} texts.")
        # Debug: Save the results to a CSV for inspection

        logging.info("Saving results to results/navier_stocker_text_results.json")
        Path("results/navier_stocker_text_results.json").parent.mkdir(parents=True, exist_ok=True)
        processed_df = pd.DataFrame(all_s)

        # Save the DataFrame to a JSON file
        json_file_path = 'results/navier_stocker_text_results.json'
        processed_df.to_json(json_file_path, orient='records', lines=True, indent=4)

        return all_s




    # Example usage:
    # self.save_all_navier_stocker_to_csv(all_s, 'results/navier_stocker_text_results.csv')

# Example usage
# sentiment_calculator = SentimentFlowCalculator(keywords_example)
# processed_df = process_speeches(df, 'path_to_senticnet.tsv')
# results = sentiment_calculator.calculate_navier_stocker_for_texts(processed_df)
# print(results)
